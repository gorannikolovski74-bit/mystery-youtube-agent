"""Research Agent — finds the most interesting unsolved mystery for the day.

Sources:
  * Reddit: r/UnresolvedMysteries, r/mystery, r/history (top posts, last week)
  * Wikipedia: pages from "Unsolved problems" / "Unexplained" categories

Claude then ranks the candidates by (1) intrigue, (2) enough information for an
~800-word script, (3) not already used (topics_done.json), and returns the best
one enriched with a factual summary built from a Wikipedia article.

Output dict:
    {
        "topic":   "The Dyatlov Pass Incident",
        "summary": "<~400-600 word factual summary for the script agent>",
        "sources": ["https://...", "https://..."]
    }

Run standalone:
    python -m agents.research_agent
    python -m agents.research_agent --topic "Dyatlov Pass Incident"
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass

import requests

from agents.common import (
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
    topic_already_used,
)

log = get_logger("research")

SUBREDDITS = ["UnresolvedMysteries", "mystery", "history"]
REDDIT_POSTS_PER_SUB = 15
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
HTTP_TIMEOUT = 20

# Wikipedia requires a descriptive User-Agent or it returns 403. Reuse one
# session for connection pooling and a consistent header across requests.
HTTP = requests.Session()
HTTP.headers.update(
    {"User-Agent": "mystery-agent/1.0 (faceless mystery channel research bot)"}
)


@dataclass
class Candidate:
    """A single mystery candidate gathered from a source."""

    title: str
    blurb: str = ""
    source: str = ""  # "reddit" | "wikipedia"
    url: str = ""
    score: int = 0  # reddit upvotes, for a rough popularity prior

    def to_prompt_line(self) -> str:
        blurb = (self.blurb or "").replace("\n", " ").strip()[:240]
        return f"- [{self.source}] {self.title} :: {blurb}"


# --- Reddit ------------------------------------------------------------------
def fetch_reddit_candidates() -> list[Candidate]:
    """Top posts from the mystery subreddits over the last week via praw.

    Returns an empty list if credentials are missing or praw is unavailable —
    the agent can still run on Wikipedia alone.
    """
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "mystery-agent/1.0")
    if not client_id or not client_secret:
        log.warning("Reddit credentials missing — skipping Reddit source.")
        return []

    try:
        import praw  # imported lazily so Wikipedia-only runs need no praw
    except ImportError:
        log.warning("praw not installed — skipping Reddit source.")
        return []

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    reddit.read_only = True

    candidates: list[Candidate] = []
    for sub in SUBREDDITS:
        try:
            for post in reddit.subreddit(sub).top(
                time_filter="week", limit=REDDIT_POSTS_PER_SUB
            ):
                if post.stickied or post.over_18:
                    continue
                candidates.append(
                    Candidate(
                        title=post.title.strip(),
                        blurb=(post.selftext or "")[:300],
                        source="reddit",
                        url=f"https://reddit.com{post.permalink}",
                        score=int(post.score),
                    )
                )
        except Exception as exc:  # one bad sub shouldn't kill the run
            log.warning("Reddit fetch failed for r/%s: %s", sub, exc)

    log.info("Collected %d Reddit candidates.", len(candidates))
    return candidates


# --- Wikipedia ---------------------------------------------------------------
def fetch_wikipedia_candidates(limit: int = 20) -> list[Candidate]:
    """Pull page titles from Wikipedia categories about unsolved/unexplained topics."""
    categories = [
        "Category:Unsolved deaths",
        "Category:Missing person cases",
        "Category:Unexplained disappearances",
        "Category:Unsolved problems",
    ]
    candidates: list[Candidate] = []
    for category in categories:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": limit,
            "cmtype": "page",
            "format": "json",
        }
        try:
            resp = HTTP.get(WIKI_API, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            members = resp.json().get("query", {}).get("categorymembers", [])
            for m in members:
                title = m["title"]
                candidates.append(
                    Candidate(
                        title=title,
                        source="wikipedia",
                        url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    )
                )
        except Exception as exc:
            log.warning("Wikipedia category fetch failed for %s: %s", category, exc)

    log.info("Collected %d Wikipedia candidates.", len(candidates))
    return candidates


def fetch_wikipedia_summary(title: str) -> tuple[str, str]:
    """Return (extract, canonical_url) for a Wikipedia page title.

    Uses the REST summary endpoint, then falls back to the extracts API for a
    longer body when the summary is too short for an 800-word script.
    """
    # 1) Short, clean summary from the REST endpoint.
    extract, url = "", ""
    try:
        resp = HTTP.get(
            f"{WIKI_REST}/page/summary/{title.replace(' ', '_')}",
            timeout=HTTP_TIMEOUT,
        )
        if resp.ok:
            data = resp.json()
            extract = data.get("extract", "")
            url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    except Exception as exc:
        log.warning("Wikipedia REST summary failed for %s: %s", title, exc)

    # 2) Longer plain-text intro for more script material.
    try:
        params = {
            "action": "query",
            "prop": "extracts",
            "exintro": False,
            "explaintext": True,
            "titles": title,
            "format": "json",
            "exchars": 4000,
        }
        resp = HTTP.get(WIKI_API, params=params, timeout=HTTP_TIMEOUT)
        if resp.ok:
            pages = resp.json().get("query", {}).get("pages", {})
            for page in pages.values():
                long_extract = page.get("extract", "")
                if len(long_extract) > len(extract):
                    extract = long_extract
    except Exception as exc:
        log.warning("Wikipedia extracts failed for %s: %s", title, exc)

    if not url:
        url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return extract.strip(), url


# --- Ranking with Claude -----------------------------------------------------
def rank_with_claude(candidates: list[Candidate]) -> list[str]:
    """Ask Claude to rank candidates and return an ordered list of topic titles."""
    # Filter out already-used topics before spending tokens.
    fresh = [c for c in candidates if not topic_already_used(c.title)]
    if not fresh:
        raise RuntimeError("No fresh candidates left after deduplication.")

    listing = "\n".join(c.to_prompt_line() for c in fresh[:60])
    prompt = (
        "You are a researcher for a faceless YouTube channel about unsolved "
        "mysteries. From the candidate list below, pick the 3 BEST topics for a "
        "750-850 word narrated video.\n\n"
        "Rank by: (1) how intriguing/mysterious it is, (2) whether there is "
        "enough public information for an ~800-word script, (3) prefer cold "
        "cases and unexplained events.\n"
        "Reject any topic that centers on a real, living, named person.\n\n"
        f"CANDIDATES:\n{listing}\n\n"
        "Respond with ONLY a JSON array of the 3 chosen topic titles, exactly as "
        'written above, best first. Example: ["Title A", "Title B", "Title C"]'
    )

    client = anthropic_client()
    resp = client.messages.create(
        model=anthropic_model(),
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    # Be forgiving about code fences / extra prose around the JSON.
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    try:
        ranked = json.loads(text)
        return [str(t).strip() for t in ranked if str(t).strip()]
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse Claude ranking, falling back to score order.")
        fresh.sort(key=lambda c: c.score, reverse=True)
        return [c.title for c in fresh[:3]]


# --- Public entry point ------------------------------------------------------
def run(topic_override: str | None = None) -> dict:
    """Find and return the topic of the day (or research a forced topic)."""
    load_env()

    if topic_override:
        log.info("Topic override provided: %s", topic_override)
        summary, url = fetch_wikipedia_summary(topic_override)
        if not summary:
            log.warning("No Wikipedia summary for override; using bare topic.")
        return {
            "topic": topic_override,
            "summary": summary,
            "sources": [url] if url else [],
        }

    candidates = fetch_reddit_candidates() + fetch_wikipedia_candidates()
    if not candidates:
        raise RuntimeError("No candidates gathered from any source.")

    ranked_titles = rank_with_claude(candidates)
    log.info("Claude ranked top topics: %s", ranked_titles)

    by_title = {c.title: c for c in candidates}
    for title in ranked_titles:
        if topic_already_used(title):
            continue
        summary, url = fetch_wikipedia_summary(title)
        # A topic needs enough material for an ~800-word script.
        if len(summary) < 500:
            log.info("Skipping '%s' — insufficient source material.", title)
            continue
        sources = [url]
        cand = by_title.get(title)
        if cand and cand.url and cand.url != url:
            sources.append(cand.url)
        result = {"topic": title, "summary": summary, "sources": sources}
        log.info("Selected topic: %s", title)
        return result

    raise RuntimeError("None of the ranked topics had enough source material.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Research agent for mystery topics.")
    parser.add_argument("--topic", help="Force a specific topic instead of ranking.")
    args = parser.parse_args()
    result = run(topic_override=args.topic)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
