#!/usr/bin/env python3
"""
Step 2 — Generate video from output/script.md

Pipeline:
  Phase 1 — Seed frame:  one text-to-image for scene 1 (flux, ~$0.003)
  Phase 2 — Clips:       image-to-video for every scene
                           scene 1: start_image_url = seed frame
                           scene N: start_image_url = last frame extracted from clip N-1
  Phase 3 — Voiceover:   ElevenLabs TTS on all narration
  Phase 4 — Stitch:      ffmpeg concat + audio mix

Usage:
  python gen_video.py
  python gen_video.py --model pro
  python gen_video.py --resume        # skip clips already done
  python gen_video.py --no-voiceover  # skip ElevenLabs step
"""

import os
import re
import sys
import json
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

FAL_KEY        = os.getenv("FAL_KEY", "")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_KEY", "")

os.environ["FAL_KEY"] = FAL_KEY

MODELS = {
    "standard": "fal-ai/kling-video/v3/standard/image-to-video",  # ~$0.29/clip
    "pro":      "fal-ai/kling-video/v3/pro/image-to-video",       # ~$0.58/clip
    "budget":   "fal-ai/kling-video/v2.1/standard/image-to-video", # ~$0.28/clip (5s)
    "wan":      "fal-ai/wan/v2.2/image-to-video",                  # ~$1.00/clip
}
COST_PER_CLIP = {"standard": 0.29, "pro": 0.58, "budget": 0.28, "wan": 1.00}

IMAGE_MODEL = "fal-ai/flux/schnell"   # seed frame only — one call per video run
IMAGE_SIZE_MAP = {
    "16:9": "landscape_16_9",
    "9:16": "portrait_9_16",
    "1:1":  "square_hd",
}

OUTPUT_DIR = Path("output")
CLIPS_DIR  = OUTPUT_DIR / "clips"
FRAMES_DIR = OUTPUT_DIR / "frames"
AUDIO_DIR  = OUTPUT_DIR / "audio"
FINAL_DIR  = OUTPUT_DIR / "final"
SCRIPT_MD  = OUTPUT_DIR / "script.md"
STATE_FILE = OUTPUT_DIR / "state.json"

# ─── CONFIG ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    defaults = {
        "model":         "standard",
        "clip_duration": 10,
        "aspect_ratio":  "16:9",
        "voice_id":      "21m00Tcm4TlvDq8ikWAM",
    }
    config_path = Path("config.yaml")
    if not config_path.exists():
        return defaults
    text = config_path.read_text(encoding="utf-8")
    for key in defaults:
        m = re.search(rf'^{key}:\s*"?([^"#\n]+?)"?\s*(?:#|$)', text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            defaults[key] = int(val) if key == "clip_duration" else val
    return defaults

# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class Scene:
    index: int
    title: str
    narration: str
    visual_prompt: str
    status: str = "pending"          # pending | done | failed
    clip_path: Optional[str] = None
    last_frame_path: Optional[str] = None

@dataclass
class Project:
    model_key: str
    seed_frame_path: Optional[str] = None   # local path of the scene-1 seed image
    scenes: list = field(default_factory=list)
    voiceover_path: Optional[str] = None
    final_path: Optional[str] = None

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    colours = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERR": "\033[91m"}
    print(f"{colours.get(level, '')}[{level}]\033[0m {msg}", flush=True)

def ensure_dirs():
    for d in [CLIPS_DIR, FRAMES_DIR, AUDIO_DIR, FINAL_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def save_state(project: Project):
    STATE_FILE.write_text(json.dumps({
        "model_key":       project.model_key,
        "seed_frame_path": project.seed_frame_path,
        "scenes":          [asdict(s) for s in project.scenes],
        "voiceover_path":  project.voiceover_path,
        "final_path":      project.final_path,
    }, indent=2), encoding="utf-8")

def load_state() -> Project:
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    p = Project(
        model_key=data["model_key"],
        seed_frame_path=data.get("seed_frame_path"),
        voiceover_path=data.get("voiceover_path"),
        final_path=data.get("final_path"),
    )
    p.scenes = [Scene(**s) for s in data["scenes"]]
    return p

def download_file(url: str, dest: Path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

# ─── PARSE SCRIPT.MD ──────────────────────────────────────────────────────────

def parse_script_md() -> list[Scene]:
    if not SCRIPT_MD.exists():
        log(f"{SCRIPT_MD} not found — run gen_script.py first", "ERR")
        sys.exit(1)

    text    = SCRIPT_MD.read_text(encoding="utf-8")
    heading = re.compile(r'^## Scene (\d+)\s*[—–\-]\s*(.+)$', re.MULTILINE)
    matches = list(heading.finditer(text))

    if not matches:
        log("No scenes found in script.md — check the ## Scene N — Title format", "ERR")
        sys.exit(1)

    scenes = []
    for i, match in enumerate(matches):
        index = int(match.group(1))
        title = match.group(2).strip()

        block_start = match.end()
        block_end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block       = text[block_start:block_end]

        narration_m = re.search(r'\*\*Narration\*\*\s*\n(.*?)(?=\n\*\*Visual\*\*)', block, re.DOTALL)
        visual_m    = re.search(r'\*\*Visual\*\*\s*\n(.*?)(?=\n---|\Z)', block, re.DOTALL)

        narration = narration_m.group(1).strip() if narration_m else ""
        visual    = visual_m.group(1).strip()    if visual_m    else ""

        if not narration or not visual:
            log(f"Scene {index} missing Narration or Visual — check script.md", "WARN")

        scenes.append(Scene(index=index, title=title, narration=narration, visual_prompt=visual))

    return scenes

# ─── PHASE 1: SEED FRAME ──────────────────────────────────────────────────────

def generate_seed_frame(scene: Scene, aspect_ratio: str) -> Optional[Path]:
    """Generate one still image from scene 1's visual prompt. Saved locally."""
    log("Phase 1 — Generating seed frame for scene 1 (flux/schnell)...")

    size = IMAGE_SIZE_MAP.get(aspect_ratio, "landscape_16_9")
    try:
        result = fal_client.subscribe(
            IMAGE_MODEL,
            arguments={
                "prompt":                scene.visual_prompt,
                "image_size":            size,
                "num_inference_steps":   4,
                "num_images":            1,
                "enable_safety_checker": False,
            },
        )
        url = result["images"][0]["url"]
    except Exception as e:
        log(f"Seed frame generation failed: {e}", "ERR")
        return None

    seed_path = FRAMES_DIR / "seed_frame.jpg"
    try:
        download_file(url, seed_path)
    except Exception as e:
        log(f"Seed frame download failed: {e}", "ERR")
        return None

    log(f"Seed frame saved → {seed_path}", "OK")
    return seed_path

# ─── PHASE 2: CLIPS ───────────────────────────────────────────────────────────

def upload_frame(frame_path: Path) -> str:
    return fal_client.upload_file(str(frame_path))

def extract_last_frame(clip_path: Path, frame_path: Path):
    subprocess.run([
        "ffmpeg", "-sseof", "-0.5", "-i", str(clip_path),
        "-frames:v", "1", "-update", "1", "-q:v", "2",
        str(frame_path), "-y", "-loglevel", "error",
    ], check=True)

def generate_clip(scene: Scene, model_endpoint: str, start_frame_url: str,
                  clip_duration: str, aspect_ratio: str) -> Optional[str]:
    def on_update(update):
        if isinstance(update, fal_client.InProgress):
            for entry in update.logs:
                print(f"    ↳ {entry['message']}", flush=True)

    try:
        result = fal_client.subscribe(
            model_endpoint,
            arguments={
                "prompt":           scene.visual_prompt,
                "start_image_url":  start_frame_url,
                "duration":         clip_duration,
                "aspect_ratio":     aspect_ratio,
                "cfg_scale":        0.5,
                "negative_prompt":  "blur, distortion, watermark, low quality, duplicate frames",
                "generate_audio":   False,
            },
            with_logs=True,
            on_queue_update=on_update,
        )
        return result["video"]["url"]
    except Exception as e:
        log(f"  Generation failed: {e}", "ERR")
        return None

# ─── PHASE 3: VOICEOVER ───────────────────────────────────────────────────────

def get_audio_duration(path: Path) -> float:
    """Return duration of an audio file in seconds using ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def fit_audio_to_duration(src: Path, dest: Path, target_seconds: float):
    """Fit audio to exactly target_seconds: speed up if too long, pad if too short.

    If narration is longer than the clip, speed it up (up to 1.3x) so nothing
    gets cut off.  If it's still over after max speedup, trim with a short
    fade-out so it doesn't cut mid-word.  Short narration is silence-padded.
    """
    actual = get_audio_duration(src)

    MAX_TEMPO = 1.3          # fastest we'll go before it sounds weird
    FADE_OUT  = 0.15         # seconds of fade when we must hard-trim

    filters = []

    if actual > target_seconds:
        tempo = min(actual / target_seconds, MAX_TEMPO)
        filters.append(f"atempo={tempo:.4f}")

        # After speedup, will the audio now fit?
        sped_duration = actual / tempo
        if sped_duration > target_seconds:
            # Still too long — fade out the last bit so it doesn't clip mid-word
            fade_start = target_seconds - FADE_OUT
            filters.append(f"afade=t=out:st={fade_start:.3f}:d={FADE_OUT}")

    # Pad with silence to fill any remaining gap
    filters.append(f"apad=whole_dur={target_seconds}")

    af = ",".join(filters)
    subprocess.run([
        "ffmpeg",
        "-i", str(src),
        "-af", af,
        "-t", str(target_seconds),
        str(dest), "-y", "-loglevel", "error",
    ], check=True)

def generate_scene_audio(scene: Scene, voice_id: str, clip_secs: float) -> Path:
    """Generate TTS audio for a single scene. Returns path to the padded file."""
    raw_path    = AUDIO_DIR / f"scene_{scene.index:03d}_raw.mp3"
    padded_path = AUDIO_DIR / f"scene_{scene.index:03d}.mp3"

    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"},
        json={
            "text":           scene.narration,
            "model_id":       "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.2},
        },
        timeout=60,
    )
    r.raise_for_status()
    raw_path.write_bytes(r.content)

    duration = get_audio_duration(raw_path)
    if duration > clip_secs:
        tempo = min(duration / clip_secs, 1.3)
        log(f"  Scene {scene.index}: narration is {duration:.1f}s vs {clip_secs}s clip → speeding up {tempo:.2f}x", "WARN")
    else:
        log(f"  Scene {scene.index}: {duration:.1f}s narration → padded to {clip_secs}s", "OK")

    fit_audio_to_duration(raw_path, padded_path, clip_secs)
    return padded_path


def concat_scene_audio(project: Project, scene_audio: list[Path], clip_secs: float):
    """Concatenate per-scene audio files into one voiceover track."""
    concat_txt = AUDIO_DIR / "audio_concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in scene_audio), encoding="utf-8")

    vo_path = AUDIO_DIR / "voiceover.mp3"
    subprocess.run([
        "ffmpeg",
        "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        "-c:a", "libmp3lame", "-q:a", "2",
        str(vo_path), "-y", "-loglevel", "error",
    ], check=True)

    project.voiceover_path = str(vo_path)
    total_s = len(scene_audio) * clip_secs
    log(f"Voiceover complete — {len(scene_audio)} scenes, {total_s:.0f}s total", "OK")


def generate_voiceover(project: Project, voice_id: str, clip_duration: str):
    if not ELEVENLABS_KEY:
        log("No ELEVENLABS_KEY — skipping voiceover", "WARN")
        return

    clip_secs   = float(clip_duration)
    done_scenes = [s for s in project.scenes if s.status == "done"]
    scene_audio = []

    log(f"Generating per-scene voiceover ({len(done_scenes)} scenes)...")

    for scene in done_scenes:
        padded_path = AUDIO_DIR / f"scene_{scene.index:03d}.mp3"

        # Skip if already generated (resume support)
        if padded_path.exists():
            log(f"  Scene {scene.index}: audio ✓ (skipping)")
            scene_audio.append(padded_path)
            continue

        scene_audio.append(generate_scene_audio(scene, voice_id, clip_secs))

    if not scene_audio:
        log("No scene audio to concatenate", "WARN")
        return

    concat_scene_audio(project, scene_audio, clip_secs)


# ─── PRE-STITCH AUDIO AUDIT ─────────────────────────────────────────────────

def audit_audio(project: Project, clip_duration: str) -> list[dict]:
    """Check every scene's raw TTS audio against clip duration.

    Returns a list of problem scenes: [{"scene": Scene, "audio_secs": float, "clip_secs": float}]
    """
    clip_secs = float(clip_duration)
    problems  = []

    for scene in project.scenes:
        if scene.status != "done":
            continue
        raw_path = AUDIO_DIR / f"scene_{scene.index:03d}_raw.mp3"
        if not raw_path.exists():
            continue
        audio_secs = get_audio_duration(raw_path)
        if audio_secs > clip_secs:
            problems.append({
                "scene":      scene,
                "audio_secs": audio_secs,
                "clip_secs":  clip_secs,
            })

    return problems


def print_audio_audit(problems: list[dict]):
    """Print a clear warning table of scenes where audio exceeds video."""
    if not problems:
        log("Audio audit: all scenes fit within clip duration ✓", "OK")
        return

    log(f"\n{'─' * 60}", "WARN")
    log(f"AUDIO AUDIT: {len(problems)} scene(s) have audio longer than video", "WARN")
    log(f"{'─' * 60}", "WARN")
    for p in problems:
        scene = p["scene"]
        over  = p["audio_secs"] - p["clip_secs"]
        log(f"  Scene {scene.index:3d} — \"{scene.title}\"", "WARN")
        log(f"           audio: {p['audio_secs']:.1f}s  |  clip: {p['clip_secs']:.1f}s  |  over by {over:.1f}s", "WARN")
        word_count = len(scene.narration.split())
        log(f"           narration ({word_count}w): \"{scene.narration[:80]}{'…' if len(scene.narration) > 80 else ''}\"", "WARN")
    log(f"{'─' * 60}", "WARN")
    log("These scenes were sped up / trimmed to fit. To fix properly:", "WARN")
    scene_list = ",".join(str(p["scene"].index) for p in problems)
    log(f"  1. Edit narration in output/script.md for scene(s): {scene_list}", "WARN")
    log(f"  2. Re-run:  python gen_video.py --fix-audio {scene_list}", "WARN")
    log(f"{'─' * 60}\n", "WARN")

# ─── PHASE 4: STITCH ──────────────────────────────────────────────────────────

def stitch_video(project: Project):
    log("Stitching final video...")

    clips = [Path(s.clip_path) for s in project.scenes if s.status == "done" and s.clip_path]
    if not clips:
        log("No completed clips to stitch!", "ERR")
        return

    concat_txt = OUTPUT_DIR / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{c.resolve()}'" for c in clips), encoding="utf-8")

    out      = FINAL_DIR / f"video_{uuid.uuid4().hex[:6]}.mp4"
    base_cmd = ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]

    if project.voiceover_path and Path(project.voiceover_path).exists():
        cmd = base_cmd + [
            "-i", project.voiceover_path,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(out), "-y", "-loglevel", "error",
        ]
    else:
        cmd = base_cmd + [
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-movflags", "+faststart",
            str(out), "-y", "-loglevel", "error",
        ]

    subprocess.run(cmd, check=True)
    project.final_path = str(out)
    log(f"Final video → {out}", "OK")

# ─── COST ESTIMATE ────────────────────────────────────────────────────────────

def print_cost_estimate(model_key: str, n_scenes: int):
    seed_cost  = 0.003  # one flux/schnell image
    video_cost = COST_PER_CLIP.get(model_key, 0.29) * n_scenes
    vo_cost    = 0.30 if ELEVENLABS_KEY else 0.0
    log(f"Estimated cost: ${seed_cost:.3f} seed + ${video_cost:.2f} video + ${vo_cost:.2f} voiceover = ~${seed_cost + video_cost + vo_cost:.2f}")

# ─── MAIN PIPELINE ────────────────────────────────────────────────────────────

def fix_audio_for_scenes(project: Project, scene_indices: list[int],
                         voice_id: str, clip_duration: str):
    """Re-read narration from script.md and regenerate audio for specific scenes.

    Video clips are untouched — only the audio files and final voiceover track
    are rebuilt.
    """
    if not ELEVENLABS_KEY:
        log("ELEVENLABS_KEY not set — cannot regenerate audio", "ERR")
        sys.exit(1)

    clip_secs = float(clip_duration)

    # Re-read narration from script.md so user edits are picked up
    fresh = {s.index: s for s in parse_script_md()}
    updated = 0
    for scene in project.scenes:
        if scene.index in scene_indices and scene.index in fresh:
            old_narration = scene.narration
            scene.narration = fresh[scene.index].narration
            if old_narration != scene.narration:
                updated += 1
                log(f"  Scene {scene.index}: narration updated from script.md", "OK")

    if updated == 0:
        log("No narration changes detected in script.md — did you edit the scenes?", "WARN")

    # Regenerate audio for the specified scenes
    log(f"\nRegenerating audio for scene(s): {', '.join(str(i) for i in scene_indices)}")
    for scene in project.scenes:
        if scene.index not in scene_indices:
            continue
        if scene.status != "done":
            log(f"  Scene {scene.index}: skipped (no video clip)", "WARN")
            continue

        # Delete old audio so it gets regenerated
        for suffix in ["_raw.mp3", ".mp3"]:
            old = AUDIO_DIR / f"scene_{scene.index:03d}{suffix}"
            if old.exists():
                old.unlink()

        generate_scene_audio(scene, voice_id, clip_secs)

    # Rebuild the full voiceover track from all per-scene audio
    log("\nRebuilding full voiceover track...")
    done_scenes = [s for s in project.scenes if s.status == "done"]
    scene_audio = []
    for scene in done_scenes:
        padded_path = AUDIO_DIR / f"scene_{scene.index:03d}.mp3"
        if padded_path.exists():
            scene_audio.append(padded_path)
        else:
            log(f"  Scene {scene.index}: missing audio — skipping", "WARN")

    if scene_audio:
        concat_scene_audio(project, scene_audio, clip_secs)
    save_state(project)


def run(model_key: str, clip_duration: str, aspect_ratio: str, voice_id: str,
        seed_override: Optional[str], resume: bool, skip_voiceover: bool,
        voiceover_only: bool = False, fix_audio: Optional[list[int]] = None):
    ensure_dirs()

    # ── --fix-audio mode: regenerate audio for specific scenes, then stitch ──
    if fix_audio:
        if not STATE_FILE.exists():
            log("No state.json found — run a full gen_video.py first", "ERR")
            sys.exit(1)
        project = load_state()
        log(f"Fix-audio mode: regenerating audio for scene(s) {', '.join(str(i) for i in fix_audio)}")
        fix_audio_for_scenes(project, fix_audio, voice_id, clip_duration)

        # Audit the fixed scenes
        problems = audit_audio(project, clip_duration)
        print_audio_audit(problems)

        log(f"\nPhase 4 — Stitch")
        stitch_video(project)
        save_state(project)

        if project.final_path:
            log(f"Output: {project.final_path}", "OK")
        return

    if not FAL_KEY and not voiceover_only:
        log("FAL_KEY not set in .env", "ERR")
        sys.exit(1)
    if model_key not in MODELS:
        log(f"Unknown model '{model_key}' — choose from: {', '.join(MODELS)}", "ERR")
        sys.exit(1)

    model_endpoint = MODELS[model_key]

    if voiceover_only:
        if not STATE_FILE.exists():
            log("No state.json found — run gen_video.py first to generate clips", "ERR")
            sys.exit(1)
        project = load_state()
        done = sum(1 for s in project.scenes if s.status == "done")
        if done == 0:
            log("No completed scenes in state.json — generate clips first", "ERR")
            sys.exit(1)
        log(f"--voiceover-only: skipping clip generation ({done} scenes found)")
    elif resume and STATE_FILE.exists():
        log("Resuming from saved state...")
        project = load_state()
        fresh   = {s.index: s for s in parse_script_md()}
        for s in project.scenes:
            if s.status != "done" and s.index in fresh:
                s.narration     = fresh[s.index].narration
                s.visual_prompt = fresh[s.index].visual_prompt
        project.model_key = model_key
    else:
        scenes  = parse_script_md()
        project = Project(model_key=model_key, scenes=scenes)
        save_state(project)

    n          = len(project.scenes)
    duration_s = n * int(clip_duration)
    log(f"Script:  {n} scenes × {clip_duration}s = {duration_s // 60}m {duration_s % 60}s")
    if not voiceover_only:
        log(f"Model:   {model_endpoint}")
        log(f"Aspect:  {aspect_ratio}")
        print_cost_estimate(model_key, n)
    print()

    if not voiceover_only:
        # ── Phase 1: seed frame ───────────────────────────────────────────────────
        # Priority: --seed CLI arg > existing state > auto-generate from scene 1
        if seed_override and Path(seed_override).exists():
            log(f"Using provided seed frame: {seed_override}")
            project.seed_frame_path = seed_override
            start_frame_url = upload_frame(Path(seed_override))
            save_state(project)
        elif project.seed_frame_path and Path(project.seed_frame_path).exists():
            log(f"Seed frame already exists — reusing {project.seed_frame_path}")
            start_frame_url = upload_frame(Path(project.seed_frame_path))
        else:
            log("No seed frame provided — auto-generating from scene 1 prompt (run gen_keyframe.py to pick manually)")
            seed_path = generate_seed_frame(project.scenes[0], aspect_ratio)
            if not seed_path:
                log("Cannot continue without a seed frame.", "ERR")
                sys.exit(1)
            project.seed_frame_path = str(seed_path)
            start_frame_url = upload_frame(seed_path)
            save_state(project)

        # ── Phase 2: clips ────────────────────────────────────────────────────────
        log(f"\nPhase 2 — Clips")
        for scene in project.scenes:
            if scene.status == "done":
                log(f"Scene {scene.index}/{n}: ✓ (skipping)")
                # Re-upload last frame to keep the chain alive on resume
                if scene.last_frame_path and Path(scene.last_frame_path).exists():
                    try:
                        start_frame_url = upload_frame(Path(scene.last_frame_path))
                    except Exception:
                        pass
                continue

            log(f"\n── Scene {scene.index}/{n}: {scene.title}")
            log(f"  start frame → scene {scene.index}")

            video_url = generate_clip(scene, model_endpoint, start_frame_url, clip_duration, aspect_ratio)

            if not video_url:
                scene.status = "failed"
                log(f"Scene {scene.index} failed — chain broken, next scene reuses last good frame", "WARN")
                save_state(project)
                continue

            clip_path = CLIPS_DIR / f"scene_{scene.index:03d}.mp4"
            download_file(video_url, clip_path)
            scene.clip_path = str(clip_path)
            log(f"  ✓ Downloaded: {clip_path.name}", "OK")

            # Extract last frame → becomes start frame for next scene
            frame_path = FRAMES_DIR / f"frame_{scene.index:03d}.jpg"
            try:
                extract_last_frame(clip_path, frame_path)
                scene.last_frame_path = str(frame_path)
                start_frame_url = upload_frame(frame_path)
                log(f"  ✓ Last frame extracted → chained to scene {scene.index + 1}", "OK")
            except Exception as e:
                log(f"  Frame extraction failed ({e}) — next scene reuses current start frame", "WARN")

            scene.status = "done"
            save_state(project)

    # ── Phase 3: voiceover ────────────────────────────────────────────────────
    if not skip_voiceover:
        log(f"\nPhase 3 — Voiceover")
        generate_voiceover(project, voice_id, clip_duration)
        save_state(project)

    # ── Pre-stitch audio audit ────────────────────────────────────────────────
    if not skip_voiceover:
        problems = audit_audio(project, clip_duration)
        print_audio_audit(problems)

    # ── Phase 4: stitch ───────────────────────────────────────────────────────
    log(f"\nPhase 4 — Stitch")
    stitch_video(project)
    save_state(project)

    done   = sum(1 for s in project.scenes if s.status == "done")
    failed = sum(1 for s in project.scenes if s.status == "failed")
    log(f"\n{'═' * 50}", "OK")
    log(f"Done: {done}/{n} scenes  |  Failed: {failed}", "OK")
    if project.final_path:
        log(f"Output: {project.final_path}", "OK")
    log(f"{'═' * 50}", "OK")


def main():
    cfg = load_config()

    ap = argparse.ArgumentParser(description="Generate video from output/script.md")
    ap.add_argument("--model", choices=list(MODELS.keys()), default=None,
                    help=f"Video model (config: {cfg['model']})")
    ap.add_argument("--seed", default=None, metavar="PATH",
                    help="Path to seed frame image (e.g. output/keyframes/option_02.jpg). "
                         "Run gen_keyframe.py first to generate options.")
    ap.add_argument("--resume", action="store_true",
                    help="Resume — skips clips already done, reuses existing seed frame")
    ap.add_argument("--no-voiceover", action="store_true",
                    help="Skip ElevenLabs voiceover step")
    ap.add_argument("--voiceover-only", action="store_true",
                    help="Skip clip generation — redo voiceover and stitch from existing clips")
    ap.add_argument("--fix-audio", default=None, metavar="SCENES",
                    help="Re-generate audio for specific scenes after editing script.md. "
                         "Comma-separated scene numbers, e.g. --fix-audio 5,12,23")
    args = ap.parse_args()

    # Parse --fix-audio scene list
    fix_audio_scenes = None
    if args.fix_audio:
        try:
            fix_audio_scenes = [int(x.strip()) for x in args.fix_audio.split(",")]
        except ValueError:
            log(f"Invalid --fix-audio value: '{args.fix_audio}' — use comma-separated numbers, e.g. 5,12,23", "ERR")
            sys.exit(1)

    run(
        model_key      = args.model or cfg["model"],
        clip_duration  = str(cfg["clip_duration"]),
        aspect_ratio   = cfg["aspect_ratio"],
        voice_id       = cfg["voice_id"],
        seed_override  = args.seed,
        resume         = args.resume,
        skip_voiceover = args.no_voiceover,
        voiceover_only = args.voiceover_only,
        fix_audio      = fix_audio_scenes,
    )


if __name__ == "__main__":
    main()
