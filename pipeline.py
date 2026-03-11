#!/usr/bin/env python3
"""
AI Video Pipeline — fal.ai edition
Produces a 10-minute video using Kling V3 (Standard) on fal.ai
with last-frame chaining for scene consistency.

Model options (swap FAL_MODEL to change):
  Kling V3 Standard  fal-ai/kling-video/v3/standard/image-to-video   ~$0.29/10s  ← default
  Kling V3 Pro       fal-ai/kling-video/v3/pro/image-to-video         ~$0.58/10s
  Kling 2.6 Pro      fal-ai/kling-video/v2.6/pro/image-to-video       ~$0.70/10s  (native audio)
  Kling 2.1 Standard fal-ai/kling-video/v2.1/standard/image-to-video  ~$0.28/5s   (cheaper test)
  Wan 2.2            fal-ai/wan/v2.2/image-to-video                   ~$1.00/10s  (open source)

Install:
  pip install fal-client requests moviepy python-dotenv

Usage:
  python video_pipeline_fal.py --topic "The rise of AI in 2025"
  python video_pipeline_fal.py --topic "Deep sea mysteries" --style "nature documentary" --model pro
  python video_pipeline_fal.py --topic "..." --resume          # resume after failure
"""

import os
import sys
import json
import time
import uuid
import argparse
import requests
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import fal_client
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ───────────────────────────────────────────────────────────────────

os.environ["FAL_KEY"] = os.getenv("FAL_KEY", "")
ANTHROPIC_KEY         = os.getenv("ANTHROPIC_KEY", "")
ELEVENLABS_KEY        = os.getenv("ELEVENLABS_KEY", "")

# Model endpoints — swap here or use --model flag
MODELS = {
    "standard": "fal-ai/kling-video/v3/standard/image-to-video",  # ~$0.29/10s
    "pro":      "fal-ai/kling-video/v3/pro/image-to-video",       # ~$0.58/10s
    "budget":   "fal-ai/kling-video/v2.1/standard/image-to-video", # ~$0.28/5s
    "wan":      "fal-ai/wan/v2.2/image-to-video",                  # ~$1.00/10s
}

OUTPUT_DIR  = Path("output")
CLIPS_DIR   = OUTPUT_DIR / "clips"
FRAMES_DIR  = OUTPUT_DIR / "frames"
AUDIO_DIR   = OUTPUT_DIR / "audio"
FINAL_DIR   = OUTPUT_DIR / "final"

CLIP_DURATION    = "10"   # seconds per clip ("5" or "10")
CLIPS_NEEDED     = 60     # 60 × 10s = 10 min
ASPECT_RATIO     = "16:9"
GENERATE_AUDIO   = False  # True = native audio per clip (costs more; use ElevenLabs instead)

# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class Scene:
    index: int
    title: str
    narration: str
    visual_prompt: str
    status: str = "pending"       # pending | generating | done | failed
    clip_path: Optional[str] = None
    last_frame_path: Optional[str] = None
    fal_request_id: Optional[str] = None

@dataclass
class Project:
    topic: str
    style: str
    model_key: str
    scenes: list = field(default_factory=list)
    voiceover_path: Optional[str] = None
    final_path: Optional[str] = None

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    colours = {"INFO":"\033[94m","OK":"\033[92m","WARN":"\033[93m","ERR":"\033[91m"}
    print(f"{colours.get(level,'')}[{level}]\033[0m {msg}", flush=True)

def ensure_dirs():
    for d in [CLIPS_DIR, FRAMES_DIR, AUDIO_DIR, FINAL_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def save_state(project: Project):
    state = {
        "topic": project.topic,
        "style": project.style,
        "model_key": project.model_key,
        "scenes": [asdict(s) for s in project.scenes],
        "voiceover_path": project.voiceover_path,
        "final_path": project.final_path,
    }
    (OUTPUT_DIR / "state.json").write_text(json.dumps(state, indent=2))

def load_state() -> Project:
    state = json.loads((OUTPUT_DIR / "state.json").read_text())
    project = Project(
        topic=state["topic"],
        style=state["style"],
        model_key=state["model_key"],
        voiceover_path=state.get("voiceover_path"),
        final_path=state.get("final_path"),
    )
    project.scenes = [Scene(**s) for s in state["scenes"]]
    return project

# ─── STEP 1: GENERATE SCRIPT WITH CLAUDE ──────────────────────────────────────

def generate_script(topic: str, style: str) -> list[Scene]:
    log(f"Generating script via Claude: '{topic}'")
    prompt = f"""You are a professional video scriptwriter. Write a script for a compelling 10-minute YouTube video.

Topic: {topic}
Visual style: {style}

Generate exactly {CLIPS_NEEDED} scenes (each ~10 seconds of screen time).
For EACH scene return a JSON object:
{{
  "index": <1-{CLIPS_NEEDED}>,
  "title": "<3-6 word title>",
  "narration": "<voiceover text, ~25 words, punchy and engaging>",
  "visual_prompt": "<detailed fal/Kling image-to-video prompt. Include: subject, action, camera movement, lighting, mood, lens. Be cinematic. Example: 'Slow aerial push-in over a rain-slicked Tokyo street at midnight, neon signs reflected in puddles, crowds with umbrellas, shallow focus, warm amber grade'>"
}}

Return ONLY a valid JSON array of {CLIPS_NEEDED} objects. No markdown, no preamble, no explanation."""

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["content"][0]["text"].strip()

    # Strip markdown fences
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    data = json.loads(text)
    scenes = [Scene(index=d["index"], title=d["title"], narration=d["narration"], visual_prompt=d["visual_prompt"]) for d in data]
    log(f"Script ready: {len(scenes)} scenes", "OK")
    return scenes

# ─── STEP 2: UPLOAD FRAME TO FAL STORAGE (no third-party needed) ───────────────

def upload_frame(frame_path: Path) -> str:
    """Upload a local file to fal's own CDN. Returns a public URL."""
    url = fal_client.upload_file(str(frame_path))
    return url

# ─── STEP 3: GENERATE CLIP VIA FAL ────────────────────────────────────────────

def generate_clip(scene: Scene, model_endpoint: str, start_frame_url: Optional[str] = None) -> Optional[str]:
    """
    Submit clip to fal.ai and block until done.
    Returns the video URL or None on failure.
    Uses fal_client.subscribe() which handles polling automatically.
    """
    args = {
        "prompt": scene.visual_prompt,
        "duration": CLIP_DURATION,
        "aspect_ratio": ASPECT_RATIO,
        "cfg_scale": 0.5,
        "negative_prompt": "blur, distortion, watermark, low quality, duplicate frames",
        "generate_audio": GENERATE_AUDIO,
    }

    if start_frame_url:
        args["image_url"] = start_frame_url
        log(f"  Scene {scene.index}: image-to-video (chained from previous)")
    else:
        log(f"  Scene {scene.index}: image-to-video (no start frame — first scene)")

    def on_update(update):
        if isinstance(update, fal_client.InProgress):
            for log_entry in update.logs:
                print(f"    ↳ {log_entry['message']}", flush=True)

    try:
        result = fal_client.subscribe(
            model_endpoint,
            arguments=args,
            with_logs=True,
            on_queue_update=on_update,
        )
        return result["video"]["url"]
    except Exception as e:
        log(f"  Generation failed: {e}", "ERR")
        return None

# ─── STEP 4: DOWNLOAD + EXTRACT LAST FRAME ────────────────────────────────────

def download_file(url: str, dest: Path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

def extract_last_frame(clip_path: Path, frame_path: Path):
    """ffmpeg: grab the very last frame of the clip."""
    subprocess.run([
        "ffmpeg", "-sseof", "-0.5", "-i", str(clip_path),
        "-frames:v", "1", "-update", "1",
        "-q:v", "2",  # high quality JPEG
        str(frame_path), "-y", "-loglevel", "error"
    ], check=True)

# ─── STEP 5: VOICEOVER (ELEVENLABS) ───────────────────────────────────────────

def generate_voiceover(project: Project):
    if not ELEVENLABS_KEY:
        log("No ElevenLabs key — skipping voiceover", "WARN")
        return

    log("Generating voiceover with ElevenLabs...")
    narration = " ".join(s.narration for s in project.scenes)

    r = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
        headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"},
        json={
            "text": narration,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.2}
        },
        timeout=120,
    )
    r.raise_for_status()

    vo_path = AUDIO_DIR / "voiceover.mp3"
    vo_path.write_bytes(r.content)
    project.voiceover_path = str(vo_path)
    log(f"Voiceover saved ({len(r.content)//1024}KB)", "OK")

# ─── STEP 6: STITCH WITH FFMPEG ───────────────────────────────────────────────

def stitch_video(project: Project):
    log("Stitching final video...")

    clips = [Path(s.clip_path) for s in project.scenes if s.status == "done" and s.clip_path]
    if not clips:
        log("No completed clips to stitch!", "ERR")
        return

    concat_txt = OUTPUT_DIR / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{c.resolve()}'" for c in clips))

    out = FINAL_DIR / f"video_{uuid.uuid4().hex[:6]}.mp4"

    if project.voiceover_path and Path(project.voiceover_path).exists():
        cmd = [
            "ffmpeg",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-i", project.voiceover_path,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(out), "-y", "-loglevel", "error"
        ]
    else:
        cmd = [
            "ffmpeg",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-movflags", "+faststart",
            str(out), "-y", "-loglevel", "error"
        ]

    subprocess.run(cmd, check=True)
    project.final_path = str(out)
    log(f"Final video: {out}", "OK")

# ─── COST ESTIMATOR ───────────────────────────────────────────────────────────

COST_PER_10S = {
    "standard": 0.29,
    "pro":      0.58,
    "budget":   0.28,
    "wan":      1.00,
}

def print_cost_estimate(model_key: str, n_scenes: int):
    cost = COST_PER_10S.get(model_key, 0.29) * n_scenes
    vo_cost = 0.30 if ELEVENLABS_KEY else 0.0
    log(f"💰 Estimated cost: ${cost:.2f} video + ~${vo_cost:.2f} voiceover = ~${cost+vo_cost:.2f} total")

# ─── MAIN PIPELINE ────────────────────────────────────────────────────────────

def run(topic: str, style: str, model_key: str, resume: bool):
    ensure_dirs()

    model_endpoint = MODELS[model_key]

    if resume and (OUTPUT_DIR / "state.json").exists():
        log("Resuming from saved state...")
        project = load_state()
    else:
        scenes = generate_script(topic, style)
        project = Project(topic=topic, style=style, model_key=model_key, scenes=scenes)
        save_state(project)

    print_cost_estimate(project.model_key, CLIPS_NEEDED)
    log(f"Model: {MODELS[project.model_key]}")
    log(f"Scenes: {len(project.scenes)} × {CLIP_DURATION}s = {int(CLIP_DURATION)*len(project.scenes)//60} min\n")

    start_frame_url = None

    for scene in project.scenes:
        if scene.status == "done":
            log(f"Scene {scene.index}: ✓ (skipping)")
            # Re-upload last frame for chaining if we're resuming mid-way
            if scene.last_frame_path and Path(scene.last_frame_path).exists():
                try:
                    start_frame_url = upload_frame(Path(scene.last_frame_path))
                except Exception:
                    start_frame_url = None
            continue

        log(f"\n── Scene {scene.index}/{len(project.scenes)}: {scene.title}")

        video_url = generate_clip(scene, model_endpoint, start_frame_url)

        if not video_url:
            scene.status = "failed"
            log(f"Scene {scene.index} failed — continuing without frame chain", "WARN")
            start_frame_url = None  # break the chain on failure
            save_state(project)
            continue

        # Download clip
        clip_path = CLIPS_DIR / f"scene_{scene.index:03d}.mp4"
        download_file(video_url, clip_path)
        scene.clip_path = str(clip_path)
        log(f"  ✓ Downloaded: {clip_path.name}", "OK")

        # Extract last frame for next scene
        frame_path = FRAMES_DIR / f"frame_{scene.index:03d}.jpg"
        try:
            extract_last_frame(clip_path, frame_path)
            scene.last_frame_path = str(frame_path)
            start_frame_url = upload_frame(frame_path)
            log(f"  ✓ Frame chained → scene {scene.index+1}", "OK")
        except Exception as e:
            log(f"  Frame extraction failed ({e}) — next scene won't chain", "WARN")
            start_frame_url = None

        scene.status = "done"
        save_state(project)

    # Voiceover
    generate_voiceover(project)
    save_state(project)

    # Stitch
    stitch_video(project)
    save_state(project)

    done = sum(1 for s in project.scenes if s.status == "done")
    failed = sum(1 for s in project.scenes if s.status == "failed")
    log(f"\n{'═'*50}", "OK")
    log(f"Done: {done}/{len(project.scenes)} scenes  |  Failed: {failed}", "OK")
    if project.final_path:
        log(f"Output: {project.final_path}", "OK")
    log(f"{'═'*50}", "OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic",  required=True)
    ap.add_argument("--style",  default="cinematic documentary")
    ap.add_argument("--model",  choices=list(MODELS.keys()), default="standard",
                    help="standard (~$17) | pro (~$35) | budget (~$17, 5s clips) | wan (~$60)")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if not os.environ["FAL_KEY"]:
        log("FAL_KEY not set in .env", "ERR"); sys.exit(1)
    if not ANTHROPIC_KEY:
        log("ANTHROPIC_KEY not set in .env", "ERR"); sys.exit(1)

    run(args.topic, args.style, args.model, args.resume)
