# Deployment Guide — Mystery YouTube Agent

End-to-end setup to run the agent on a DigitalOcean Droplet (Ubuntu 24) and
publish daily videos automatically.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv \
    ffmpeg libcairo2-dev libpango1.0-dev pkg-config imagemagick
```

## 2. Project + Python deps

```bash
git clone <your-repo-url> mystery-agent
cd mystery-agent
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

## 3. Kokoro TTS model files (one-time download)

```bash
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin
# Keep them in the project root, or point KOKORO_MODEL / KOKORO_VOICES at them.
```

## 4. Secrets

```bash
cp config/apis.env.example config/apis.env
nano config/apis.env   # fill in the keys below
```

| Key | Where to get it | Required for |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys | research, script, thumbnail, SEO |
| `REDDIT_CLIENT_ID` / `_SECRET` | reddit.com/prefs/apps (script app) | richer research (optional) |
| `YOUTUBE_CLIENT_ID` / `_SECRET` | Google Cloud OAuth (step 6) | upload |
| `TELEGRAM_BOT_TOKEN` / `CHAT_ID` | @BotFather / your chat id | alerts (optional) |

## 5. Background music (optional)

Drop one royalty-free track into `assets/music/` (mp3/wav). The assembly agent
mixes the first file it finds, quietly under the narration.

## 6. YouTube OAuth (one-time)

1. **Create the YouTube channel** for your Google account at youtube.com
   (this is a manual step — the API uploads to an *existing* channel).
2. In **console.cloud.google.com**: create a project → enable **YouTube
   Data API v3** → **OAuth consent screen** (External, add yourself as a test
   user) → **Credentials → Create OAuth client ID → Desktop app**.
3. Either put `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` in `config/apis.env`,
   or download the JSON as `config/client_secret.json`.
4. Authorize once (over SSH with port forwarding so the browser callback works):
   ```bash
   ssh -L 8080:localhost:8080 user@droplet
   python -m agents.upload_agent --auth
   ```
   This writes `config/token.json`. After that, uploads are fully automatic.

> ⚠️ **Privacy lock:** until Google audits your API project, public uploads are
> forced to `private`. Keep `YOUTUBE_PRIVACY=private` (default) and review the
> first videos manually. Once verified, set `YOUTUBE_PRIVACY=public`.

## 7. Test step by step

```bash
# No keys needed:
python run_pipeline.py --steps research --topic "Tunguska event"

# With ANTHROPIC_API_KEY:
python run_pipeline.py --steps research,script --topic "Dyatlov Pass incident"

# With Kokoro + ffmpeg:
python run_pipeline.py --steps research,script,tts,animation,assembly \
    --topic "Dyatlov Pass incident"

# Full run (also thumbnail + upload + alert):
python run_pipeline.py
```

## 8. Daily cron

```bash
crontab -e
# Run every day at 08:00, from the venv:
0 8 * * * cd /home/ubuntu/mystery-agent && /home/ubuntu/mystery-agent/.venv/bin/python run_pipeline.py >> logs/cron.log 2>&1
```

---

## Pipeline at a glance

```
research → script → tts → animation → assembly → thumbnail → upload → alert
```

Each agent has a `run()` entry point and degrades gracefully when an optional
credential is missing. Intermediate media lands in `output/` (git-ignored).
