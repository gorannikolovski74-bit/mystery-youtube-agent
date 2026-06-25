# Mystery YouTube Agent

Fully automated, faceless YouTube channel for unsolved mysteries. Each day the
pipeline researches a topic, writes a script, generates narration and stickman
animation, assembles the video, makes a thumbnail, uploads to YouTube, and
sends a Telegram notification.

```
research → script → tts → animation → assembly → thumbnail → upload → alert
```

## Status

| Step       | Agent                       | Status        |
|------------|-----------------------------|---------------|
| research   | `agents/research_agent.py`  | ✅ implemented |
| script     | `agents/script_agent.py`    | ✅ implemented |
| tts        | `agents/tts_agent.py`       | ✅ implemented |
| animation  | `agents/animation_agent.py` | ✅ implemented |
| assembly   | `agents/assembly_agent.py`  | 🚧 placeholder |
| thumbnail  | `agents/thumbnail_agent.py` | 🚧 placeholder |
| upload     | `agents/upload_agent.py`    | 🚧 placeholder |
| alert      | `agents/alert_agent.py`     | ✅ implemented |

## Quick start

System packages (Ubuntu) needed for animation/assembly:

```bash
sudo apt update && sudo apt install -y ffmpeg libcairo2-dev libpango1.0-dev pkg-config
```

```bash
pip install -r requirements.txt
cp config/apis.env.example config/apis.env   # then fill in your keys

# Research + script for a forced topic:
python run_pipeline.py --steps research,script --topic "Dyatlov Pass incident"

# Full daily run (auto topic selection):
python run_pipeline.py
```

## Configuration

Copy `config/apis.env.example` → `config/apis.env` and fill in:

- `ANTHROPIC_API_KEY` — for topic ranking and script writing.
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — optional; without them the
  research agent falls back to Wikipedia only.
- `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` — for upload (later step).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — for alerts.

Channel tone, structure and visual rules live in `config/style_profile.md`.

## Daily cron (on the server)

```bash
0 8 * * * cd /home/ubuntu/mystery-agent && python run_pipeline.py >> logs/cron.log 2>&1
```

## Notes

- Code comments are in English.
- Secrets (`config/apis.env`) and generated media (`output/`) are git-ignored.
- Agents degrade gracefully when optional credentials are missing.
