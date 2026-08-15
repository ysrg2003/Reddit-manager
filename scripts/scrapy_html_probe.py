from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

import requests
from scrapy import Selector


def first_key() -> str:
    raw = (os.getenv("SCRAPER_API_KEYS_JSON") or "").strip()
    if not raw:
        raise SystemExit("SCRAPER_API_KEYS_JSON is not available")
    values = json.loads(raw)
    if not isinstance(values, list):
        raise SystemExit("SCRAPER_API_KEYS_JSON must be a JSON array")
    for item in values:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            for field in ("key", "api_key", "token", "secret", "value"):
                if item.get(field):
                    return str(item[field]).strip()
    raise SystemExit("SCRAPER_API_KEYS_JSON contains no usable key")


def summarize(content: str) -> dict[str, object]:
    selector = Selector(text=content or "")
    tag_counts = Counter(selector.xpath("name()") for _ in [])
    for node in selector.xpath("//*"):
        name = node.root.tag if hasattr(node.root, "tag") else ""
        if isinstance(name, str):
            tag_counts[name.lower()] += 1
    links = []
    for anchor in selector.css("a[href]"):
        href = anchor.attrib.get("href", "")
        if "/comments/" in href and len(links) < 40:
            links.append({"href": href[:300], "text": " ".join(anchor.css("::text").getall()).strip()[:240]})
    return {
        "title": " ".join(selector.css("title::text").getall()).strip()[:240],
        "body_text_sample": " ".join(selector.css("body ::text").getall()).strip()[:1000],
        "tag_counts": dict(tag_counts.most_common(40)),
        "comment_links": links,
        "old_thing_count": len(selector.css("div.thing")),
        "comment_node_count": len(selector.css("div.comment")),
        "shreddit_post_count": len(selector.css("shreddit-post")),
        "title_anchor_count": len(selector.css("a.title")),
        "challenge_markers": [marker for marker in ("prove your humanity", "captcha", "blocked", "robot") if marker in content.lower()],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one public Reddit HTML page through ScraperAPI and summarize it with Scrapy")
    parser.add_argument("--output-dir", default="artifacts/scrapy-html-probe")
    parser.add_argument("--timeout", type=float, default=70.0)
    parser.add_argument("--render", action="store_true", help="Ask ScraperAPI to render the target page")
    args = parser.parse_args()
    query = urlencode({"q": "vibe coding trap why building assisted", "limit": 5, "sort": "relevance", "t": "all", "raw_json": 1})
    target = f"https://old.reddit.com/search.json?{query}"
    response = requests.get(
        "https://api.scraperapi.com",
        params={"api_key": first_key(), "url": target, "render": "true" if args.render else "false"},
        timeout=args.timeout,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "old_search_response.html").write_text(response.text, encoding="utf-8")
    report = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "body_length": len(response.content),
        "render_requested": args.render,
        "summary": summarize(response.text),
        "security_note": "The ScraperAPI key is not stored in this report or HTML artifact.",
    }
    (output / "scrapy_html_structure.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"status={response.status_code} content_type={report['content_type']} bytes={report['body_length']}", flush=True)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
