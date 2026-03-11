#!/usr/bin/env python3
"""
Step 1.5 — Generate seed frame options → output/keyframes/

Generates multiple image variations from scene 1's visual prompt so you can
pick the best starting frame before committing to video generation.

Usage:
  python gen_keyframe.py                    # 4 variations, fast model
  python gen_keyframe.py --count 8          # 8 variations
  python gen_keyframe.py --model quality    # flux-pro for higher fidelity
  python gen_keyframe.py --prompt "custom prompt override"

Then pass your chosen image to gen_video.py:
  python gen_video.py --seed output/keyframes/option_03.jpg
"""

import os
import re
import sys
import argparse
from pathlib import Path

import fal_client
import requests
from dotenv import load_dotenv

load_dotenv()

FAL_KEY = os.getenv("FAL_KEY", "")
os.environ["FAL_KEY"] = FAL_KEY

IMAGE_MODELS = {
    "fast":    ("fal-ai/flux/schnell",    4,  "$0.003/image", {"enable_safety_checker": False}),
    "quality": ("fal-ai/flux-pro/v1.1",  28,  "$0.05/image",  {"safety_tolerance": "5"}),
}

IMAGE_SIZE_MAP = {
    "16:9": "landscape_16_9",
    "9:16": "portrait_9_16",
    "1:1":  "square_hd",
}

OUTPUT_DIR   = Path("output")
KEYS_DIR     = OUTPUT_DIR / "keyframes"
SCRIPT_MD    = OUTPUT_DIR / "script.md"
CONFIG_PATH  = Path("config.yaml")

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    colours = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERR": "\033[91m"}
    print(f"{colours.get(level, '')}[{level}]\033[0m {msg}", flush=True)

def load_aspect_ratio() -> str:
    if not CONFIG_PATH.exists():
        return "16:9"
    m = re.search(r'^aspect_ratio:\s*"?([^"#\n]+?)"?\s*(?:#|$)', CONFIG_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1).strip() if m else "16:9"

def get_seed_prompt() -> str:
    """
    Reads the ## Seed Frame Prompt section from script.md.
    Falls back to Scene 1's Visual prompt if the section is missing.
    """
    if not SCRIPT_MD.exists():
        log(f"{SCRIPT_MD} not found — run gen_script.py first", "ERR")
        sys.exit(1)

    text = SCRIPT_MD.read_text(encoding="utf-8")

    # Try dedicated seed frame section first
    seed_match = re.search(
        r'^## Seed Frame Prompt\s*\n+.*?\n+(.*?)(?=\n---|\n##|\Z)',
        text, re.DOTALL | re.MULTILINE
    )
    if seed_match:
        prompt = seed_match.group(1).strip()
        if prompt:
            log("Using ## Seed Frame Prompt from script.md")
            return prompt

    # Fallback: Scene 1 visual prompt
    log("No ## Seed Frame Prompt found — falling back to Scene 1 Visual prompt", "WARN")
    log("Add a '## Seed Frame Prompt' section to script.md for better results", "WARN")
    scene1_match = re.search(
        r'## Scene 1\s*[—–\-].*?\*\*Visual\*\*\s*\n(.*?)(?=\n---|\Z)',
        text, re.DOTALL
    )
    if not scene1_match:
        log("Could not find Scene 1 Visual prompt in script.md", "ERR")
        sys.exit(1)

    return scene1_match.group(1).strip()

def download_file(url: str, dest: Path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

# ─── GENERATION ───────────────────────────────────────────────────────────────

def generate_options(prompt: str, count: int, model_key: str, aspect_ratio: str) -> list[Path]:
    model_id, steps, cost_label, extra_args = IMAGE_MODELS[model_key]
    size = IMAGE_SIZE_MAP.get(aspect_ratio, "landscape_16_9")

    log(f"Model:   {model_id} ({cost_label})")
    log(f"Count:   {count} variations")
    log(f"Aspect:  {aspect_ratio}")
    log(f"Prompt:  {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    print()

    saved = []

    for i in range(1, count + 1):
        log(f"Generating option {i}/{count}...")
        try:
            result = fal_client.subscribe(
                model_id,
                arguments={
                    "prompt":              prompt,
                    "image_size":          size,
                    "num_inference_steps": steps,
                    "num_images":          1,
                    **extra_args,
                },
            )
            url  = result["images"][0]["url"]
            dest = KEYS_DIR / f"option_{i:02d}.jpg"
            download_file(url, dest)
            saved.append(dest)
            log(f"  ✓ Saved → {dest}", "OK")
        except Exception as e:
            log(f"  Option {i} failed: {e}", "ERR")

    return saved

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not FAL_KEY:
        log("FAL_KEY not set in .env", "ERR")
        sys.exit(1)

    KEYS_DIR.mkdir(parents=True, exist_ok=True)

    ap = argparse.ArgumentParser(description="Generate seed frame options for gen_video.py")
    ap.add_argument("--count",  type=int, default=4,
                    help="Number of image variations to generate (default: 4)")
    ap.add_argument("--model",  choices=["fast", "quality"], default="fast",
                    help="fast=flux/schnell (~$0.003) | quality=flux-pro (~$0.05) (default: fast)")
    ap.add_argument("--prompt", default=None,
                    help="Override prompt (default: uses Scene 1 visual prompt from script.md)")
    args = ap.parse_args()

    aspect_ratio = load_aspect_ratio()
    prompt       = args.prompt or get_seed_prompt()

    log("─" * 50)
    log("Seed Frame Generator")
    log("─" * 50)

    saved = generate_options(prompt, args.count, args.model, aspect_ratio)

    if not saved:
        log("No images were generated successfully.", "ERR")
        sys.exit(1)

    print()
    log("─" * 50, "OK")
    log(f"Generated {len(saved)} options in output/keyframes/", "OK")
    log("─" * 50, "OK")
    print()
    print("  Open the images and pick your favourite, then run:")
    print()
    for path in saved:
        print(f"    python gen_video.py --seed {path}")
    print()


if __name__ == "__main__":
    main()
