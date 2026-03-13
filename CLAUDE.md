# AI YouTube Video Pipeline

Automated YouTube video production using Claude (script), Kling/Wan via fal.ai (video), ElevenLabs (voiceover), and ffmpeg (stitching). Split into two steps so you can review and edit the script before spending money on video generation.

## Architecture

```
style_profile.md  (built by /analyze-channel)
  → /gen-ideas    →  brief.md            (you pick an idea)
  → gen_script.py →  output/script.md   (you review + edit this)
  → /critique-script → output/script.md (optionally rewritten)
  → gen_video.py  →  output/clips/      (Kling/Wan via fal.ai, frame-chained)
                  →  output/audio/      (ElevenLabs voiceover)
                  →  output/final/      (ffmpeg stitched MP4)
```

## Key Files

| File | Purpose |
|---|---|
| `brief.md` | Your video concept — fill this in or generate with `/gen-ideas` |
| `style_profile.md` | Style analysis of reference channels — built by `/analyze-channel` |
| `gen_script.py` | Step 1: sends brief to Claude, outputs `output/script.md` |
| `gen_video.py` | Step 2: reads script.md, generates clips, stitches final video |
| `gen_keyframe.py` | Optional: generates seed frame image variations to pick from |
| `tools/fetch_transcripts.py` | Helper: fetches YouTube transcripts (called by `/analyze-channel`) |
| `dashboard.jsx` | React monitoring UI (mock simulation, not wired to pipeline) |
| `output/script.md` | Human-editable scene list — edit narration + visuals here |
| `output/state.json` | Resume state — tracks clip status, paths |
| `pipeline.py` | Original monolithic script (reference only) |

## Full Workflow (with style analysis)

```bash
# 0. Activate venv
venv\Scripts\activate

# 1. Analyze channels you want to emulate (run once per channel)
/analyze-channel https://youtube.com/@Kurzgesagt --count 20

# 2. Generate video ideas for your topic
/gen-ideas "your topic here"
# → pick an idea, brief.md is written automatically

# 3. Generate the script (cheap — ~$0.02)
python gen_script.py --duration 3

# 4. Critique and optionally rewrite the script
/critique-script

# 5. (Optional) Generate seed frame variations to pick from
python gen_keyframe.py

# 6. Generate video (expensive — ~$17 for 10 min standard)
python gen_video.py

# Resume after a failure
python gen_video.py --resume

# Re-generate voiceover only (no new clips)
python gen_video.py --voiceover-only

# Fix audio for specific scenes after editing script.md
python gen_video.py --fix-audio 3,7,12
```

## Claude Code Slash Commands

These run inside Claude Code (type in chat, not terminal).

| Command | Usage | Purpose |
|---|---|---|
| `/analyze-channel` | `/analyze-channel <url> [--count N]` | Fetch top N video transcripts, analyze style, append to `style_profile.md` |
| `/gen-ideas` | `/gen-ideas <topic description>` | Generate 7 video ideas from style profile, write chosen idea to `brief.md` |
| `/critique-script` | `/critique-script` | Score script against style profile, optionally rewrite `output/script.md` |

Command files live in `.claude/commands/`. Run multiple `/analyze-channel` calls to build a multi-channel style profile — sections are appended, not overwritten.

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
| `--voiceover-only` | off | Re-generate audio only, re-stitch |
| `--fix-audio` | off | Re-record specific scenes e.g. `--fix-audio 3,7` |
| `--seed` | auto | Path to seed frame image for scene 1 |

## Models

| Key | Endpoint | Cost/clip |
|---|---|---|
| standard | fal-ai/kling-video/v3/standard/image-to-video | ~$0.29 |
| pro | fal-ai/kling-video/v3/pro/image-to-video | ~$0.58 |
| budget | fal-ai/kling-video/v2.1/standard/image-to-video | ~$0.28 (5s clips) |
| wan | fal-ai/wan/v2.2/image-to-video | ~$1.00 |

## Frame Chaining

After each clip downloads, ffmpeg grabs the last frame (`.jpg`), uploads it to fal CDN, and passes it as `start_image_url` to the next Kling call. This keeps character, lighting, and continuity consistent. On failure the chain breaks silently and the next scene starts fresh.

## Resume Behaviour

`output/state.json` tracks every scene's status (`pending | done | failed`), clip path, and last-frame path. On `--resume`, scene statuses are loaded from state.json but narration/visual are re-read from `script.md` — so edits you make after a partial run are picked up.

## Environment Variables (.env)

```
FAL_KEY=...            # required for video generation
ANTHROPIC_KEY=...      # required for script generation
ELEVENLABS_KEY=...     # optional — skip for no voiceover
YOUTUBE_API_KEY=...    # optional — enables sort-by-views in /analyze-channel
```

See `.env.example` for full documentation.

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
