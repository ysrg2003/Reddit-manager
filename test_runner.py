"""CLI runner for deliberate Reddit-related research.

The default provider is ``auto``: direct Reddit is disabled by default, then
an explicitly configured free-credit Brave Search API is used as a discovery
fallback. Network access remains explicit and bounded.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from reddit_manager import RedditManager, generate_writer_brief


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Reddit research evidence")
    parser.add_argument("--query", default=os.getenv("TEST_KEYWORD"), help="Research query")
    parser.add_argument("--provider", default=os.getenv("REDDIT_PROVIDER", "scraperapi"), choices=["auto", "reddit", "scraperapi", "brave"], help="Evidence transport")
    parser.add_argument("--output-dir", default="artifacts", help="Directory for evidence artifacts")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--posts-per-page", type=int, default=10)
    parser.add_argument("--comments-limit", type=int, default=100)
    parser.add_argument("--sort", default="relevance", choices=["relevance", "hot", "top", "new", "comments"])
    parser.add_argument("--time-window", default="all", choices=["all", "year", "month", "week", "day"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.query or not args.query.strip():
        raise SystemExit("Provide --query or TEST_KEYWORD before a network run.")

    manager = RedditManager()
    bundle = manager.search_with_fallback(
        args.query,
        provider=args.provider,
        pages=args.pages,
        posts_per_page=args.posts_per_page,
        comments_limit=args.comments_limit,
        sort=args.sort,
        time_window=args.time_window,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "reddit_evidence.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "reddit_evidence.md").write_text(generate_writer_brief(bundle), encoding="utf-8")

    media = []
    for post in bundle.get("posts", []):
        for url in post.get("media", []):
            media.append({"url": url, "source": post.get("url"), "evidence_status": "unverified_user_generated_content"})
    (output / "reddit_media.json").write_text(json.dumps(media, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Provider: {args.provider}")
    print(f"Transport: {bundle.get('transport', 'unknown')}")
    print(f"Collected {len(bundle.get('posts', []))} Reddit-related evidence items for: {args.query}")
    print(f"Artifacts: {output / 'reddit_evidence.json'}, {output / 'reddit_evidence.md'}")
    if bundle.get("warnings"):
        print(f"Warnings: {len(bundle['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
