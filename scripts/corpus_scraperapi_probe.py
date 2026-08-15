from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from reddit_manager import RedditManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded ScraperAPI probe for the 50-article corpus")
    parser.add_argument("--queries", default="testdata/corpus_queries.json")
    parser.add_argument("--output-dir", default="artifacts/corpus")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--posts-per-page", type=int, default=1)
    parser.add_argument("--comments-limit", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (os.getenv("SCRAPER_API_KEY") or os.getenv("SCRAPER_API_KEYS_JSON") or os.getenv("AI_ROUTER_SCRAPERAPI_KEYS_JSON")):
        raise SystemExit("SCRAPER_API_KEYS_JSON is not available in this GitHub Actions environment.")

    query_file = Path(args.queries)
    payload = json.loads(query_file.read_text(encoding="utf-8"))
    articles = payload.get("articles") or []
    if len(articles) != 50:
        raise SystemExit(f"Expected 50 article queries, found {len(articles)}.")

    manager = RedditManager()
    results = []
    quota_stopped = False
    for index, item in enumerate(articles, 1):
        if quota_stopped:
            results.append({
                "article_number": index,
                "article_file": item["article_file"],
                "title": item["title"],
                "query": item["query"],
                "status": "skipped_after_quota_or_rate_limit",
                "transport": "not_run",
                "posts": 0,
                "warnings": ["Skipped after ScraperAPI quota/rate-limit signal to avoid further usage."],
            })
            continue
        bundle = manager.search_with_fallback(
            item["query"],
            provider="scraperapi",
            pages=args.pages,
            posts_per_page=args.posts_per_page,
            comments_limit=args.comments_limit,
        )
        posts = bundle.get("posts") or []
        warnings = [str(value) for value in (bundle.get("warnings") or [])]
        quota_signal = any("quota" in warning.lower() or "rate limit" in warning.lower() or "429" in warning for warning in warnings)
        if posts:
            status = "evidence_found"
        elif quota_signal:
            status = "quota_or_rate_limited"
            quota_stopped = True
        elif warnings:
            status = "transport_or_query_warning"
        else:
            status = "no_matching_reddit_posts"
        results.append({
            "article_number": index,
            "article_file": item["article_file"],
            "title": item["title"],
            "section": item["section"],
            "query": item["query"],
            "status": status,
            "transport": bundle.get("transport", "unknown"),
            "posts": len(posts),
            "post_urls": [post.get("url") for post in posts if post.get("url")],
            "warnings": warnings,
            "retrieved_at": bundle.get("retrieved_at"),
        })
        print(f"[{index:02d}/50] {status}: {item['article_file']}", flush=True)
        time.sleep(0.2)

    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "scraperapi",
        "article_count": len(results),
        "counts": counts,
        "results": results,
        "security_note": "No API key values or Reddit post bodies are stored in this report.",
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "corpus_scraperapi_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Corpus ScraperAPI Probe",
        "",
        f"Provider: `scraperapi`",
        f"Articles tested: `{len(results)}`",
        "",
        "## Counts",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| `{status}` | {count} |" for status, count in sorted(counts.items()))
    lines.extend([
        "",
        "> This is a transport and discovery probe. Reddit posts and comments remain user-generated evidence and are not verified facts.",
        "> API key values and post bodies are intentionally excluded from the artifact.",
        "",
        "## Per-article results",
        "",
        "| # | Article | Status | Posts | Query |",
        "|---:|---|---|---:|---|",
    ])
    lines.extend(f"| {r['article_number']} | `{r['article_file']}` | `{r['status']}` | {r['posts']} | {r['query']} |" for r in results)
    (output_dir / "corpus_scraperapi_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
