#!/usr/bin/env python3
"""
Fetch transcripts from a YouTube channel's top videos.

Usage:
    python tools/fetch_transcripts.py --channel https://youtube.com/@Kurzgesagt --count 20
    python tools/fetch_transcripts.py --channel @Veritasium --count 15 --out tools/veritasium.json

Requires:
    pip install youtube-transcript-api yt-dlp

Optional (enables sort by views):
    YOUTUBE_API_KEY in .env
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def log(msg, level="INFO"):
    prefix = {"INFO": "[INFO]", "OK": "[OK]  ", "WARN": "[WARN]", "ERR": "[ERR] "}.get(level, "[INFO]")
    print(f"{prefix} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Channel slug from URL / handle
# ---------------------------------------------------------------------------

def channel_slug(channel: str) -> str:
    """Return a filesystem-safe slug for naming the output file."""
    slug = re.sub(r"https?://(www\.)?youtube\.com/", "", channel)
    slug = slug.lstrip("@").rstrip("/")
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)
    return slug.lower()[:40]


# ---------------------------------------------------------------------------
# Video ID retrieval — YouTube Data API v3
# ---------------------------------------------------------------------------

def get_video_ids_api(channel: str, count: int, api_key: str) -> list[dict]:
    """Return list of {id, title, view_count} sorted by views descending."""
    import requests

    base = "https://www.googleapis.com/youtube/v3"

    # Resolve channel handle / URL → channel ID
    handle = re.sub(r"https?://(www\.)?youtube\.com/@?", "", channel).lstrip("@").rstrip("/")
    r = requests.get(f"{base}/channels", params={"part": "contentDetails", "forHandle": handle, "key": api_key}, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise ValueError(f"Channel not found for handle: {handle}")

    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    log(f"Uploads playlist: {uploads_playlist}")

    # Collect video IDs from playlist (over-fetch to get enough for view sort)
    fetch_target = min(count * 3, 200)
    video_ids = []
    page_token = None
    while len(video_ids) < fetch_target:
        params = {"part": "contentDetails", "playlistId": uploads_playlist, "maxResults": 50, "key": api_key}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{base}/playlistItems", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        for item in data.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    log(f"Found {len(video_ids)} videos in uploads playlist")

    # Batch fetch view counts (50 per request)
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        r = requests.get(f"{base}/videos", params={
            "part": "snippet,statistics", "id": ",".join(batch), "key": api_key
        }, timeout=15)
        r.raise_for_status()
        for item in r.json().get("items", []):
            videos.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "view_count": int(item["statistics"].get("viewCount", 0)),
            })

    videos.sort(key=lambda v: v["view_count"], reverse=True)
    return videos[:count]


# ---------------------------------------------------------------------------
# Video ID retrieval — yt-dlp fallback
# ---------------------------------------------------------------------------

def get_video_ids_ytdlp(channel: str, count: int) -> list[dict]:
    """Return list of {id, title, view_count} using yt-dlp (no API key needed)."""
    # Normalise to a channel URL yt-dlp understands
    if not channel.startswith("http"):
        channel = f"https://www.youtube.com/@{channel.lstrip('@')}"
    channel_videos_url = channel.rstrip("/") + "/videos"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end", str(count * 2),
        "--print", "%(id)s\t%(title)s\t%(view_count)s",
        "--no-warnings",
        channel_videos_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        log("yt-dlp not found. Install with: pip install yt-dlp", "ERR")
        sys.exit(1)

    if result.returncode != 0:
        log(f"yt-dlp failed: {result.stderr.strip()}", "ERR")
        sys.exit(1)

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        vid_id = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        try:
            view_count = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip() not in ("", "NA", "None") else 0
        except ValueError:
            view_count = 0
        videos.append({"id": vid_id, "title": title, "view_count": view_count})

    # Sort by views if yt-dlp returned them; otherwise keep upload order
    if any(v["view_count"] > 0 for v in videos):
        videos.sort(key=lambda v: v["view_count"], reverse=True)
    else:
        log("View counts unavailable from yt-dlp — using upload order (newest first)", "WARN")
        log("Add YOUTUBE_API_KEY to .env to enable sort-by-views", "WARN")

    return videos[:count]


# ---------------------------------------------------------------------------
# Transcript fetching
# ---------------------------------------------------------------------------

def fetch_transcript(video_id: str, max_words: int) -> tuple[str | None, str | None]:
    """Returns (transcript_text, error_message). transcript_text is None on failure."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
    except ImportError:
        log("youtube-transcript-api not installed. Run: pip install youtube-transcript-api", "ERR")
        sys.exit(1)

    try:
        entries = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
        words = " ".join(e["text"] if isinstance(e, dict) else e.text for e in entries).split()
        if max_words and len(words) > max_words:
            words = words[:max_words]
        return " ".join(words), None
    except Exception as e:
        return None, type(e).__name__


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube channel transcripts")
    parser.add_argument("--channel", required=True, help="Channel URL, @handle, or channel ID")
    parser.add_argument("--count", type=int, default=20, help="Number of videos to fetch (default: 20)")
    parser.add_argument("--out", default=None, help="Output JSON file path (default: tools/transcripts_<slug>.json)")
    parser.add_argument("--max-words", type=int, default=3000, help="Max words per transcript (default: 3000)")
    args = parser.parse_args()

    slug = channel_slug(args.channel)
    out_path = args.out or f"tools/transcripts_{slug}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()

    log(f"Channel: {args.channel}")

    if api_key:
        log("Sort method: views (YouTube Data API v3)")
        sort_method = "views"
        try:
            videos = get_video_ids_api(args.channel, args.count, api_key)
        except Exception as e:
            log(f"YouTube API failed ({e}), falling back to yt-dlp", "WARN")
            sort_method = "recent_or_views"
            videos = get_video_ids_ytdlp(args.channel, args.count)
    else:
        log("No YOUTUBE_API_KEY found — using yt-dlp (add key to .env for sort-by-views)", "WARN")
        sort_method = "recent_or_views"
        videos = get_video_ids_ytdlp(args.channel, args.count)

    log(f"Fetching transcripts ({len(videos)} videos)...")

    results = []
    ok_count = 0
    for i, video in enumerate(videos, 1):
        transcript, error = fetch_transcript(video["id"], args.max_words)
        word_count = len(transcript.split()) if transcript else 0
        view_str = f"{video['view_count']:,}" if video["view_count"] else "?"
        if transcript:
            log(f"{i:2}/{len(videos)} {video['title'][:50]} — {view_str} views ({word_count} words)", "OK")
            ok_count += 1
        else:
            log(f"{i:2}/{len(videos)} {video['title'][:50]} — {error}", "WARN")
        results.append({
            "id": video["id"],
            "title": video["title"],
            "view_count": video["view_count"],
            "transcript": transcript,
            "error": error,
        })

    output = {
        "channel": args.channel,
        "channel_slug": slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sort_method": sort_method,
        "videos": results,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    log(f"Saved -> {out_path} ({ok_count}/{len(videos)} transcripts)", "OK")
    if ok_count == 0:
        log("No transcripts fetched — channel may have disabled captions", "WARN")


if __name__ == "__main__":
    main()
