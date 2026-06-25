"""Upload Agent — uploads the final video to YouTube (Data API v3).

Responsibilities:
  * Generate SEO metadata (title, description, tags) with Claude.
  * Authenticate via OAuth2 (token cached in config/token.json after the
    one-time consent).
  * Upload the video (resumable) and set the custom thumbnail.

OAuth setup (one-time, see DEPLOY.md):
  * Enable "YouTube Data API v3" in Google Cloud.
  * Create OAuth client credentials (Desktop app).
  * Put YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET in config/apis.env
    (or drop the downloaded client_secret.json into config/).
  * Run `python -m agents.upload_agent --auth` once to produce token.json.

Privacy: defaults to 'private' (YOUTUBE_PRIVACY). New/unverified API projects
have their public uploads locked to private by YouTube until the project passes
Google's audit — keep it private until then, switch to 'public' afterwards.

Returns: the YouTube watch URL.
"""
from __future__ import annotations

import argparse
import json
import os

from agents.common import (
    CONFIG_DIR,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("upload")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # needed to set thumbnail
]
TOKEN_FILE = CONFIG_DIR / "token.json"
CLIENT_SECRET_FILE = CONFIG_DIR / "client_secret.json"
CATEGORY_EDUCATION = "27"

BASE_TAGS = [
    "unsolved mysteries", "true mysteries", "unexplained events",
    "mystery channel", "cold case", "documentary",
]


# --- SEO metadata ------------------------------------------------------------
def _seo_metadata(topic: dict) -> dict:
    """Generate {title, description, tags} via Claude, with a fallback."""
    name = topic.get("topic", "An Unsolved Mystery")
    summary = topic.get("summary", "")
    try:
        client = anthropic_client()
        prompt = (
            "You are a YouTube SEO expert for a faceless unsolved-mysteries "
            "channel. For the topic below, produce JSON with keys "
            '"title", "description", "tags".\n'
            "- title: format '<Mystery> That STILL Baffles Experts...', <=90 chars\n"
            "- description: 2-3 sentence hook, then the line 'What do YOU think "
            "happened? Let us know in the comments.'\n"
            "- tags: array of 8-12 lowercase keyword phrases\n"
            "Never mention real living people.\n\n"
            f"TOPIC: {name}\n\nSUMMARY:\n{summary[:1500]}\n\n"
            "Reply with ONLY the JSON object."
        )
        resp = client.messages.create(
            model=anthropic_model(),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        start, end = text.find("{"), text.rfind("}")
        meta = json.loads(text[start : end + 1])
        meta.setdefault("title", f"{name} That STILL Baffles Experts...")
        meta.setdefault("description", "")
        tags = meta.get("tags") or []
        meta["tags"] = list(dict.fromkeys([*tags, *BASE_TAGS]))[:15]
        return meta
    except Exception as exc:
        log.warning("Claude SEO generation failed (%s) — using fallback.", exc)
        return {
            "title": f"{name} That STILL Baffles Experts..."[:90],
            "description": (
                f"The mystery of {name} has never been explained.\n\n"
                "What do YOU think happened? Let us know in the comments."
            ),
            "tags": BASE_TAGS,
        }


# --- OAuth -------------------------------------------------------------------
def _client_config() -> dict | None:
    """Build an OAuth client config from env vars, if both are present."""
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not cid or not secret:
        return None
    return {
        "installed": {
            "client_id": cid,
            "client_secret": secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _get_credentials(interactive: bool = False):
    """Load cached credentials, refreshing or running the OAuth flow as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if not interactive:
        raise RuntimeError(
            "No valid YouTube credentials. Run `python -m agents.upload_agent "
            "--auth` once to authorize (see DEPLOY.md)."
        )

    # Interactive one-time consent.
    if CLIENT_SECRET_FILE.exists():
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE), SCOPES
        )
    else:
        config = _client_config()
        if not config:
            raise RuntimeError(
                "Provide config/client_secret.json or set YOUTUBE_CLIENT_ID and "
                "YOUTUBE_CLIENT_SECRET in config/apis.env."
            )
        flow = InstalledAppFlow.from_client_config(config, SCOPES)

    # run_local_server works over an SSH tunnel; falls back to console URL.
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    log.info("Saved OAuth token to %s", TOKEN_FILE)
    return creds


def authorize() -> None:
    """Run the one-time interactive OAuth flow and cache the token."""
    load_env()
    _get_credentials(interactive=True)
    print(f"Authorized. Token saved to {TOKEN_FILE}")


# --- Upload ------------------------------------------------------------------
def run(video: str, thumb: str | None, topic: dict) -> str:
    """Upload the video (+ thumbnail) to YouTube and return the watch URL."""
    load_env()
    if not os.path.exists(video):
        raise FileNotFoundError(f"Video file missing: {video}")

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is not installed. "
            "Run `pip install google-api-python-client google-auth-oauthlib`."
        ) from exc

    meta = _seo_metadata(topic)
    log.info("Uploading with title: %s", meta["title"])

    creds = _get_credentials(interactive=False)
    youtube = build("youtube", "v3", credentials=creds)

    privacy = os.environ.get("YOUTUBE_PRIVACY", "private")
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": CATEGORY_EDUCATION,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload progress: %d%%", int(status.progress() * 100))

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    log.info("Uploaded: %s (privacy=%s)", url, privacy)

    # Custom thumbnail (best-effort; needs the force-ssl scope).
    if thumb and os.path.exists(thumb):
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(thumb)
            ).execute()
            log.info("Thumbnail set.")
        except Exception as exc:
            log.warning("Could not set thumbnail: %s", exc)

    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a video to YouTube.")
    parser.add_argument("--auth", action="store_true",
                        help="Run the one-time OAuth consent and exit.")
    parser.add_argument("--video", help="Path to the video file.")
    parser.add_argument("--thumb", help="Path to the thumbnail image.")
    parser.add_argument("--topic", help="Topic title (for metadata).")
    args = parser.parse_args()

    if args.auth:
        authorize()
        return
    if not args.video or not args.topic:
        parser.error("--video and --topic are required (or use --auth).")
    url = run(args.video, args.thumb, {"topic": args.topic})
    print(url)


if __name__ == "__main__":
    main()
