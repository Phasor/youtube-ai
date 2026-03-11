# AI YouTube Video Pipeline

Automated YouTube video production using Claude (script), Kling/Wan via fal.ai (video), ElevenLabs (voiceover), and ffmpeg (stitching). Split into two steps so you can review and edit the script before spending money on video generation.

## Architecture

```
brief.md  (you write this)
  → gen_script.py  →  output/script.md  (you review + edit this)
  → gen_video.py   →  output/clips/     (Kling/Wan via fal.ai, frame-chained)
                   →  output/audio/     (ElevenLabs voiceover)
                   →  output/final/     (ffmpeg stitched MP4)
```

## Key Files

| File | Purpose |
|---|---|
| `brief.md` | Your video concept — fill this in before running anything |
| `gen_script.py` | Step 1: sends brief to Claude, outputs `output/script.md` |
| `gen_video.py` | Step 2: reads script.md, generates clips, stitches final video |
| `dashboard.jsx` | React monitoring UI (mock simulation, not wired to pipeline) |
| `output/script.md` | Human-editable scene list — edit narration + visuals here |
| `output/state.json` | Resume state — tracks clip status, paths |
| `pipeline.py` | Original monolithic script (reference only) |

## Workflow

```bash
# 1. Fill in your video concept
nano brief.md

# 2. Generate the script (cheap — ~$0.02)
python gen_script.py --duration 10

# 3. Review and edit output/script.md — tweak narration and visual prompts

# 4. Generate video (expensive — ~$17 for 10 min standard)
python gen_video.py

# Resume after a failure
python gen_video.py --resume

# Skip voiceover
python gen_video.py --no-voiceover
```

## output/script.md Format

Each scene is a section with a strict heading format (used for parsing):

```markdown
## Scene 1 — Title Here

**Narration**
Spoken voiceover text here.

**Visual**
Detailed Kling AI prompt here.
```

Do not change the `## Scene N — Title` heading structure. Everything else is free-form.

## gen_script.py Options

| Flag | Default | Notes |
|---|---|---|
| `--duration` | 10 | Target video length in minutes |
| `--brief` | brief.md | Path to brief file |

Claude determines scene count from the story — roughly 6 scenes per minute.

## gen_video.py Options

| Flag | Default | Notes |
|---|---|---|
| `--model` | standard | standard / pro / budget / wan |
| `--resume` | off | Skip scenes already marked done |
| `--no-voiceover` | off | Skip ElevenLabs step |

## Models

| Key | Endpoint | Cost/clip |
|---|---|---|
| standard | fal-ai/kling-video/v3/standard/image-to-video | ~$0.29 |
| pro | fal-ai/kling-video/v3/pro/image-to-video | ~$0.58 |
| budget | fal-ai/kling-video/v2.1/standard/image-to-video | ~$0.28 (5s clips) |
| wan | fal-ai/wan/v2.2/image-to-video | ~$1.00 |

## Frame Chaining

After each clip downloads, ffmpeg grabs the last frame (`.jpg`), uploads it to fal CDN, and passes it as `image_url` to the next Kling call. This keeps character, lighting, and continuity consistent. On failure the chain breaks silently and the next scene starts fresh.

## Resume Behaviour

`output/state.json` tracks every scene's status (`pending | done | failed`), clip path, and last-frame path. On `--resume`, scene statuses are loaded from state.json but narration/visual are re-read from `script.md` — so edits you make after a partial run are picked up.

## Environment Variables (.env)

```
FAL_KEY=...          # required for video generation
ANTHROPIC_KEY=...    # required for script generation
ELEVENLABS_KEY=...   # optional — skip for no voiceover
```

## Cost Estimate (standard model, 10 min video, ~60 scenes)
- Video: 60 × $0.29 = **~$17.40**
- Voiceover: **~$0.30** (ElevenLabs, ~1500 words)
- Claude script: **~$0.02**
- **Total: ~$17.72**

## Dashboard (optional)

```bash
npm install && npm run dev
```
Vite + React — mock simulation only, not connected to real pipeline.
