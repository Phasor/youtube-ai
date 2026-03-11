#!/usr/bin/env python3
"""
Step 1 — Generate script from brief.md → output/script.md

Claude reads your brief, decides the right number of scenes for the requested duration,
and writes a full script. Review and edit output/script.md before running gen_video.py.

Settings are read from config.yaml — run `python setup.py` to configure.
CLI flags override config.yaml values.

Usage:
  python gen_script.py
  python gen_script.py --duration 5
  python gen_script.py --brief my_brief.md
"""

import os
import sys
import json
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY", "")
OUTPUT_DIR    = Path("output")

# ─── CONFIG ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    defaults = {"brief": "brief.md", "duration": 10, "clip_duration": 10}
    config_path = Path("config.yaml")
    if not config_path.exists():
        return defaults
    import re
    text = config_path.read_text(encoding="utf-8")
    for key in defaults:
        m = re.search(rf'^{key}:\s*"?([^"#\n]+?)"?\s*(?:#|$)', text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            defaults[key] = int(val) if key in ("duration", "clip_duration") else val
    return defaults

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    colours = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERR": "\033[91m"}
    print(f"{colours.get(level, '')}[{level}]\033[0m {msg}", flush=True)

def read_brief(path: Path) -> str:
    if not path.exists():
        log(f"Brief not found: {path}", "ERR")
        log("Fill in brief.md with your video concept and run again.", "ERR")
        sys.exit(1)
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        log("brief.md is empty — add your video concept first.", "ERR")
        sys.exit(1)
    return content

# ─── SCRIPT GENERATION ────────────────────────────────────────────────────────

def generate_script(brief: str, duration_minutes: int, clip_seconds: int) -> dict:
    """Returns {"seed_prompt": str, "scenes": list[dict]}"""
    target_scenes = duration_minutes * 60 // clip_seconds
    word_limit    = max_words(clip_seconds)

    log(f"Sending brief to Claude (target ~{target_scenes} scenes for {duration_minutes} min, ≤{word_limit} words/scene)...")

    prompt = f"""You are a professional video scriptwriter. Based on the brief below, write a compelling YouTube video script.

BRIEF:
{brief}

TARGET DURATION: approximately {duration_minutes} minutes
CLIP LENGTH: each scene will be rendered as exactly {clip_seconds} seconds of video
SCENE COUNT: write as many scenes as the story genuinely needs — roughly {target_scenes} scenes for {duration_minutes} minutes (do not pad with filler scenes, do not rush the narrative — let the story breathe)

Return a single JSON object with two keys:

"seed_prompt": A still-image prompt (for flux image generation) that establishes the art style, character design, colour palette, and world. This image sets the visual DNA for the entire video — every video clip will chain from it. Write it as a detailed description of a single composed still frame, NOT as a video action. Include: character design, art style, environment, lighting, colour palette. Example: "Cute cartoon earthworm character with large expressive eyes, smooth 2D flat animation style, underground cross-section view, warm earthy tones, Kurzgesagt-inspired design, clean bold outlines, soft ambient lighting, high detail still frame"

"scenes": An array of scene objects, each with:
{{
  "index": <integer starting at 1>,
  "title": "<3-6 word scene title>",
  "narration": "<voiceover text — MUST be {word_limit} words or fewer. This is a hard limit: the voiceover must finish well before the {clip_seconds}s clip ends so audio never gets cut off. Be punchy and concise, written as spoken word.>",
  "visual_prompt": "<detailed prompt for Kling AI image-to-video. Describe: subject, action, camera movement, lighting, mood. Be cinematic. The visual style should be consistent with the seed_prompt art style.>"
}}

Return ONLY the raw JSON object. No markdown fences, no preamble, no commentary."""

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 16000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    r.raise_for_status()

    text = r.json()["content"][0]["text"].strip()

    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    data = json.loads(text)
    # Handle both {"seed_prompt":..., "scenes":[...]} and bare array (fallback)
    if isinstance(data, list):
        return {"seed_prompt": "", "scenes": data}
    return data

# ─── MARKDOWN OUTPUT ──────────────────────────────────────────────────────────

def scenes_to_markdown(result: dict, brief: str, duration_minutes: int, clip_seconds: int) -> str:
    scenes      = result["scenes"]
    seed_prompt = result.get("seed_prompt", "")

    title = "Untitled"
    for line in brief.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            title = stripped
            break

    actual_s   = len(scenes) * clip_seconds
    actual_min = actual_s // 60
    actual_sec = actual_s % 60

    lines = [
        f"# {title}",
        f"",
        f"**Scenes:** {len(scenes)}  |  **Duration:** ~{actual_min}m {actual_sec}s  |  **Clip length:** {clip_seconds}s each",
        f"",
        f"> **How to edit:** Change any Narration or Visual text freely.",
        f"> Add or remove scenes by copying/deleting scene blocks.",
        f"> Keep the `## Scene N — Title` heading format — it is used for parsing.",
        f"> When done: `python gen_video.py`",
        f"",
        f"---",
        f"",
        f"## Seed Frame Prompt",
        f"",
        f"A still image that establishes the art style, character design, and world. "
        f"This is passed to `gen_keyframe.py` and sets the visual DNA for the entire video — "
        f"every clip will chain from this image forward.",
        f"",
        seed_prompt if seed_prompt else "<!-- Add your seed frame prompt here -->",
        f"",
        f"---",
        f"",
    ]

    for s in scenes:
        lines += [
            f"## Scene {s['index']} — {s['title']}",
            f"",
            f"**Narration**",
            s["narration"],
            f"",
            f"**Visual**",
            s["visual_prompt"],
            f"",
            f"---",
            f"",
        ]

    return "\n".join(lines)

# ─── NARRATION LENGTH FIX ─────────────────────────────────────────────────────

# ElevenLabs speaks at roughly 150 wpm. We target 80% of clip duration for
# narration so there's a comfortable silence buffer at the end of each scene.
SPEECH_WPM     = 150
AUDIO_BUFFER   = 0.80   # use 80% of clip time for speech → 20% safety margin

def max_words(clip_seconds: int) -> int:
    """Max narration words that fit in clip_seconds with the audio buffer."""
    return int(clip_seconds * AUDIO_BUFFER / 60 * SPEECH_WPM)

def fix_narration_lengths(scenes: list[dict], clip_seconds: int) -> list[dict]:
    """
    Find narrations that are too long for their clip and shorten them with Claude.
    Returns scenes list (modified in place, also returned for clarity).
    """
    limit     = max_words(clip_seconds)
    too_long  = [s for s in scenes if len(s["narration"].split()) > limit]

    if not too_long:
        log(f"All narrations within {limit}-word limit ({clip_seconds}s clips) ✓", "OK")
        return scenes

    log(f"{len(too_long)} narration(s) exceed {limit} words — shortening with Claude...")

    # Build a single batch request to avoid multiple API calls
    items = "\n".join(
        f'{i+1}. Scene {s["index"]} ({len(s["narration"].split())} words): "{s["narration"]}"'
        for i, s in enumerate(too_long)
    )

    prompt = f"""Shorten the following video narrations so each fits within {limit} words (must finish within {int(clip_seconds * AUDIO_BUFFER)}s of a {clip_seconds}s clip).

Rules:
- Keep the core meaning, tone, and punchy style
- Each narration must be UNDER {limit} words
- Return ONLY a JSON array of objects: [{{"index": <scene index>, "narration": "<shortened text>"}}]
- No markdown, no explanation

Narrations to shorten:
{items}"""

    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model":      "claude-sonnet-4-20250514",
            "max_tokens": 4000,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    r.raise_for_status()

    text = r.json()["content"][0]["text"].strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    fixes = {item["index"]: item["narration"] for item in json.loads(text)}

    for scene in scenes:
        if scene["index"] in fixes:
            old_words = len(scene["narration"].split())
            scene["narration"] = fixes[scene["index"]]
            new_words = len(scene["narration"].split())
            log(f"  Scene {scene['index']}: {old_words}w → {new_words}w", "OK")

    return scenes

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()

    ap = argparse.ArgumentParser(description="Generate video script from brief.md")
    ap.add_argument("--duration", type=int, default=None,
                    help=f"Target video length in minutes (config: {cfg['duration']})")
    ap.add_argument("--brief", default=None,
                    help=f"Path to brief file (config: {cfg['brief']})")
    args = ap.parse_args()

    # CLI overrides config
    duration     = args.duration if args.duration is not None else cfg["duration"]
    brief_path   = Path(args.brief) if args.brief else Path(cfg["brief"])
    clip_seconds = cfg["clip_duration"]

    if not ANTHROPIC_KEY:
        log("ANTHROPIC_KEY not set in .env", "ERR")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log(f"Brief:    {brief_path}")
    log(f"Duration: {duration} min  |  Clip: {clip_seconds}s each")

    brief = read_brief(brief_path)
    result   = generate_script(brief, duration, clip_seconds)
    result["scenes"] = fix_narration_lengths(result["scenes"], clip_seconds)
    scenes   = result["scenes"]
    actual_s = len(scenes) * clip_seconds
    log(f"Script ready: {len(scenes)} scenes = {actual_s // 60}m {actual_s % 60}s", "OK")
    if result.get("seed_prompt"):
        log("Seed frame prompt included", "OK")

    script_path = OUTPUT_DIR / "script.md"
    script_path.write_text(scenes_to_markdown(result, brief, duration, clip_seconds), encoding="utf-8")
    log(f"Saved → {script_path}", "OK")
    log("Review output/script.md, then run: python gen_keyframe.py", "OK")


if __name__ == "__main__":
    main()
