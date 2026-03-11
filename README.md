# YouTube AI Video Pipeline

Automatically generate a full YouTube video from a text brief. Claude writes the script, Kling AI (via fal.ai) generates video clips with frame-chaining for visual consistency, ElevenLabs narrates each scene, and ffmpeg stitches everything into a final MP4.

## How It Works

```
brief.md  →  gen_script.py  →  output/script.md  (review + edit)
                            →  gen_keyframe.py   →  output/keyframes/  (pick seed image)
                            →  gen_video.py      →  output/final/video.mp4
```

Each step is separate so you can review and edit the script before spending money on video generation.

---

## Prerequisites

- **Python 3.10+** — [python.org](https://www.python.org/downloads/) (check "Add python.exe to PATH" on Windows)
- **ffmpeg** — [ffmpeg.org](https://ffmpeg.org/download.html) (must be on PATH)
- API keys for the services you want to use (see below)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Phasor/youtube-ai.git
cd youtube-ai
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
FAL_KEY=your_fal_key_here            # required — video generation
ANTHROPIC_KEY=your_anthropic_key     # required — script generation
ELEVENLABS_KEY=your_elevenlabs_key   # optional — voiceover narration
```

| Key | Where to get it |
|-----|----------------|
| `FAL_KEY` | [fal.ai/dashboard/keys](https://fal.ai/dashboard/keys) |
| `ANTHROPIC_KEY` | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) |
| `ELEVENLABS_KEY` | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) |

### 4. Configure pipeline settings

Run the interactive setup wizard:

```bash
python setup.py
```

This lets you choose video model, clip duration, aspect ratio, and voice. Settings are saved to `config.yaml`.

---

## Usage

### Step 1 — Write your brief

Edit `brief.md` with your video concept, target audience, style, and story beats. Be as detailed as you like.

### Step 2 — Generate the script

```bash
python gen_script.py
```

Claude reads `brief.md` and writes a full scene-by-scene script to `output/script.md`. Each scene has a narration (voiceover text) and a visual prompt (Kling AI instruction).

**Options:**
```bash
python gen_script.py --duration 5        # target 5 minutes (default: from config.yaml)
python gen_script.py --brief my_idea.md  # use a different brief file
```

**Review and edit `output/script.md` before continuing.** You can freely change narration text and visual prompts. Keep the `## Scene N — Title` heading format — it is used for parsing.

### Step 3 — Generate seed frame

Pick the visual style for your video by generating image options:

```bash
python gen_keyframe.py
```

This generates 4 image variations from your script's seed prompt and saves them to `output/keyframes/`. Open the images and pick your favourite.

**Options:**
```bash
python gen_keyframe.py --count 8           # generate 8 options instead of 4
python gen_keyframe.py --model quality     # use flux-pro for higher fidelity (~$0.05/image vs $0.003)
python gen_keyframe.py --prompt "custom"   # override the prompt
```

### Step 4 — Generate the video

```bash
python gen_video.py --seed output/keyframes/option_02.jpg
```

This runs the full pipeline:
1. Uses your chosen seed frame as the first clip's starting image
2. Generates each video clip via Kling AI, chaining the last frame of each clip to the next (visual consistency)
3. Generates per-scene voiceover via ElevenLabs, padded to exact clip duration
4. Stitches everything into `output/final/video.mp4`

**Options:**
```bash
python gen_video.py --seed output/keyframes/option_02.jpg   # use a specific seed frame
python gen_video.py --model pro                              # override video model
python gen_video.py --resume                                 # resume after a failure
python gen_video.py --no-voiceover                          # skip ElevenLabs step
python gen_video.py --voiceover-only                        # redo voice + stitch, keep existing clips
```

---

## Output Structure

```
output/
  script.md          # generated script — edit this before running gen_video.py
  state.json         # resume state (clip status, paths)
  keyframes/
    option_01.jpg    # seed frame options — pick one for gen_video.py
    option_02.jpg
    ...
  clips/
    scene_001.mp4    # individual video clips
    scene_002.mp4
    ...
  frames/
    frame_001.jpg    # last frame of each clip (used for chaining)
    ...
  audio/
    scene_001.mp3    # per-scene voiceover (padded to clip duration)
    voiceover.mp3    # concatenated full voiceover track
  final/
    video.mp4        # final stitched video
```

---

## Video Models

| Model | Endpoint | Cost/clip | Notes |
|-------|----------|-----------|-------|
| `standard` | Kling V3 Standard | ~$0.29 | Best value, good quality |
| `pro` | Kling V3 Pro | ~$0.58 | Higher quality, better for complex scenes |
| `budget` | Kling V2.1 Standard | ~$0.28 | Older model, 5s clips only |
| `wan` | Wan 2.2 | ~$1.00 | Open-source alternative, different style |

Set in `config.yaml` or override with `--model`.

---

## Cost Estimates

| Video length | Scenes | Standard model | + Voiceover | Total |
|---|---|---|---|---|
| 2 min | ~12 | ~$3.50 | ~$0.10 | **~$3.60** |
| 5 min | ~30 | ~$8.70 | ~$0.20 | **~$8.90** |
| 10 min | ~60 | ~$17.40 | ~$0.30 | **~$17.70** |

Script generation (Claude) adds ~$0.02 regardless of length.

---

## Resuming After a Failure

If generation fails mid-run, use `--resume` to pick up where you left off:

```bash
python gen_video.py --resume
```

`output/state.json` tracks every scene's status. Completed scenes are skipped. If you edited `script.md` after the partial run, the updated narration and visual prompts are picked up automatically.

---

## Changing the Voice

Find voices at [elevenlabs.io/voice-library](https://elevenlabs.io/voice-library). Copy the voice ID and either:

- Run `python setup.py` and choose option `6) Custom` to paste your voice ID
- Or edit `config.yaml` directly: `voice_id: "your_voice_id_here"`

To regenerate voiceover without re-generating clips:

```bash
python gen_video.py --voiceover-only
```

---

## config.yaml Reference

```yaml
brief: brief.md          # path to your brief file
duration: 2              # target video length in minutes
model: standard          # video model: standard / pro / budget / wan
clip_duration: 10        # seconds per clip: 5 or 10
aspect_ratio: "16:9"     # 16:9 | 9:16 | 1:1
voice_id: "..."          # ElevenLabs voice ID
```

All values can be overridden with CLI flags. Run `python setup.py` to configure interactively.
