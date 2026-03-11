#!/usr/bin/env python3
"""
Interactive setup wizard — writes config.yaml

Run before your first video (or any time you want to change settings):
  python setup.py
"""

from pathlib import Path

CONFIG_PATH = Path("config.yaml")

MODELS = {
    "1": ("standard", "Kling V3 Standard", "$0.29/clip", "Best value. Good quality for most content."),
    "2": ("pro",      "Kling V3 Pro",      "$0.58/clip", "Higher quality. Better for complex scenes."),
    "3": ("budget",   "Kling V2.1 Budget", "$0.28/clip", "Older model, 5s clips. Good for quick tests."),
    "4": ("wan",      "Wan 2.2",           "$1.00/clip", "Open source alternative. Different visual style."),
}

ASPECTS = {
    "1": ("16:9",  "Landscape (YouTube standard)"),
    "2": ("9:16",  "Vertical (YouTube Shorts / TikTok)"),
    "3": ("1:1",   "Square (Instagram)"),
}

VOICES = {
    "1": ("21m00Tcm4TlvDq8ikWAM", "Rachel",  "Clear, neutral narrator. Works for most content."),
    "2": ("AZnzlk1XvdvUeBnXmlld", "Domi",    "Energetic, younger feel. Good for kids content."),
    "3": ("EXAVITQu4vr4xnSDxMaL", "Bella",   "Warm and friendly. Good for storytelling."),
    "4": ("ErXwobaYiN019PkySvjV", "Antoni",  "Smooth male voice. Good for documentary style."),
    "5": ("pNInz6obpgDQGcFmaJgB", "Adam",    "Deep, authoritative. Good for serious topics."),
    "6": (None,                   "Custom",  "Enter your own ElevenLabs voice ID."),
}

def ask(prompt, default=None):
    display = f" [{default}]" if default is not None else ""
    raw = input(f"{prompt}{display}: ").strip()
    return raw if raw else str(default) if default is not None else ""

def section(title):
    print(f"\n  {title}")
    print(f"  {'─' * len(title)}")

def main():
    print("\n┌─────────────────────────────────────────┐")
    print("│      AI Video Pipeline — Setup          │")
    print("└─────────────────────────────────────────┘")

    # Load existing config as defaults
    existing = {}
    if CONFIG_PATH.exists():
        import re
        text = CONFIG_PATH.read_text(encoding="utf-8")
        for key in ["brief", "duration", "model", "clip_duration", "aspect_ratio", "voice_id"]:
            m = re.search(rf'^{key}:\s*"?([^"#\n]+?)"?\s*(?:#|$)', text, re.MULTILINE)
            if m:
                existing[key] = m.group(1).strip()
        print(f"\n  Existing config found — press Enter to keep current values.\n")

    # ── Brief ─────────────────────────────────────────────────────────────────
    section("Brief file")
    brief = ask("  Path to your brief file", existing.get("brief", "brief.md"))

    # ── Duration ──────────────────────────────────────────────────────────────
    section("Video duration")
    duration = ask("  Target length in minutes", existing.get("duration", "2"))

    # ── Model ─────────────────────────────────────────────────────────────────
    section("Video model")
    print()
    for k, (key, name, cost, desc) in MODELS.items():
        marker = "◆" if existing.get("model") == key else " "
        print(f"    {marker} {k}) {name:<24} {cost:<12} {desc}")
    print()

    try:
        duration_int  = int(duration)
        clip_dur_hint = 5 if existing.get("model") == "budget" else 10
        n_clips_hint  = duration_int * 60 // clip_dur_hint
    except ValueError:
        n_clips_hint = "?"

    current_model_num = next((k for k, (key, *_) in MODELS.items() if key == existing.get("model")), "1")
    model_choice = ask(f"  Choose model [1-4]", current_model_num)
    model_key, model_name, model_cost, _ = MODELS.get(model_choice, MODELS["1"])

    # ── Clip duration ─────────────────────────────────────────────────────────
    section("Clip length")
    if model_key == "budget":
        print("  Budget model supports 5s clips only.")
        clip_duration = "5"
    else:
        clip_duration = ask("  Seconds per clip (5 or 10)", existing.get("clip_duration", "10"))
        if clip_duration not in ("5", "10"):
            clip_duration = "10"

    # Recalculate estimate with chosen settings
    try:
        n_clips = int(duration) * 60 // int(clip_duration)
        cost_estimate = n_clips * float(model_cost.replace("$", "").replace("/clip", ""))
        print(f"\n  Estimate: {n_clips} clips × {model_cost} = ${cost_estimate:.2f} video cost")
    except Exception:
        pass

    # ── Aspect ratio ──────────────────────────────────────────────────────────
    section("Aspect ratio")
    print()
    for k, (ratio, label) in ASPECTS.items():
        marker = "◆" if existing.get("aspect_ratio") == ratio else " "
        print(f"    {marker} {k}) {ratio:<8} {label}")
    print()
    current_aspect_num = next((k for k, (r, _) in ASPECTS.items() if r == existing.get("aspect_ratio")), "1")
    aspect_choice = ask("  Choose aspect ratio [1-3]", current_aspect_num)
    aspect_ratio, _ = ASPECTS.get(aspect_choice, ASPECTS["1"])

    # ── Voice ─────────────────────────────────────────────────────────────────
    section("ElevenLabs voice (optional — skip if no ELEVENLABS_KEY)")
    print()
    for k, (vid, name, desc) in VOICES.items():
        marker = "◆" if existing.get("voice_id") == vid else " "
        print(f"    {marker} {k}) {name:<12} {desc}")
    print()
    current_voice_num = next((k for k, (v, *_) in VOICES.items() if v == existing.get("voice_id")), "1")
    voice_choice = ask("  Choose voice [1-6]", current_voice_num)
    voice_id, voice_name, _ = VOICES.get(voice_choice, VOICES["1"])
    if voice_id is None:
        voice_id = ask("  Paste your ElevenLabs voice ID", existing.get("voice_id", ""))
        voice_name = "Custom"

    # ── Write config ──────────────────────────────────────────────────────────
    config = f"""# ─── AI Video Pipeline Config ────────────────────────────────────────────────
# Edit directly or run: python setup.py

# ── Script generation ─────────────────────────────────────────────────────────

brief: {brief}            # path to your brief file
duration: {duration}              # target video length in minutes

# ── Video model ───────────────────────────────────────────────────────────────
# standard  fal-ai/kling-video/v3/standard   ~$0.29/clip   best value
# pro       fal-ai/kling-video/v3/pro        ~$0.58/clip   higher quality
# budget    fal-ai/kling-video/v2.1/standard ~$0.28/clip   older, 5s clips
# wan       fal-ai/wan/v2.2                  ~$1.00/clip   open source alt

model: {model_key}

# ── Clip settings ─────────────────────────────────────────────────────────────

clip_duration: {clip_duration}        # seconds per clip: 5 or 10 (budget model uses 5)
aspect_ratio: "{aspect_ratio}"     # 16:9 (landscape) | 9:16 (vertical/Shorts) | 1:1 (square)

# ── Voiceover ─────────────────────────────────────────────────────────────────

voice_id: "{voice_id}"   # {voice_name}
"""

    CONFIG_PATH.write_text(config, encoding="utf-8")

    print(f"""
┌─────────────────────────────────────────┐
│  Config saved to config.yaml            │
└─────────────────────────────────────────┘

  Model:        {model_name} ({model_cost})
  Duration:     {duration} min
  Aspect:       {aspect_ratio}
  Clip length:  {clip_duration}s
  Voice:        {voice_name}

  Next steps:
    1. Edit brief.md with your video concept
    2. python gen_script.py     → generate output/script.md
    3. Review and edit script.md
    4. python gen_video.py      → generate the video
""")


if __name__ == "__main__":
    main()
