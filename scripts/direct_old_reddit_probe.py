from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


POST_URL = "https://old.reddit.com/r/AI_Agents/comments/1vkb9yy/the_biggest_trap_ive_hit_doing_vibe_coding_as/"


def shape_json(payload: Any) -> dict[str, Any]:
    shape: dict[str, Any] = {"root_type": type(payload).__name__}
    if not isinstance(payload, list):
        if isinstance(payload, dict):
            shape["root_keys"] = sorted(payload.keys())
        return shape
    shape["root_length"] = len(payload)
    if payload and isinstance(payload[0], dict):
        shape["first_keys"] = sorted(payload[0].keys())
        data = payload[0].get("data")
        if isinstance(data, dict):
            children = data.get("children")
            shape["first_listing_children"] = len(children) if isinstance(children, list) else None
            if children and isinstance(children[0], dict):
                child_data = children[0].get("data")
                if isinstance(child_data, dict):
                    shape["post_fields"] = sorted(
                        key for key in ("title", "selftext", "subreddit", "author", "score", "num_comments", "permalink", "url")
                        if key in child_data
                    )
                    shape["selftext_length"] = len(child_data.get("selftext") or "")
    if len(payload) > 1 and isinstance(payload[1], dict):
        shape["second_keys"] = sorted(payload[1].keys())
        data = payload[1].get("data")
        if isinstance(data, dict):
            children = data.get("children")
            shape["comment_children"] = len(children) if isinstance(children, list) else None
            shape["comment_more_nodes"] = sum(
                1 for child in (children or [])
                if isinstance(child, dict) and child.get("kind") == "more"
            )
    return shape


def request_one(session: requests.Session, label: str, url: str, timeout: float) -> dict[str, Any]:
    try:
        response = session.get(
            url,
            headers={"User-Agent": "YusufRedditResearch/1.0 (research evidence collector)"},
            timeout=timeout,
            allow_redirects=False,
        )
        result: dict[str, Any] = {
            "target": label,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body_length": len(response.content),
            "redirect_location": response.headers.get("location", ""),
        }
        if response.status_code == 200 and "json" in response.headers.get("content-type", "").lower():
            try:
                result["json_shape"] = shape_json(response.json())
            except ValueError:
                result["json_shape"] = {"root_type": "invalid_json"}
        return result
    except requests.RequestException as exc:
        return {
            "target": label,
            "status_code": None,
            "error_type": type(exc).__name__,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe old.reddit.com JSON directly without ScraperAPI")
    parser.add_argument("--output-dir", default="artifacts/direct-old-reddit")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    query = urlencode({"q": "vibe coding trap why building assisted", "limit": 5, "sort": "relevance", "t": "all", "raw_json": 1})
    search_url = f"https://old.reddit.com/search.json?{query}"
    post_url = POST_URL.rstrip("/") + "/.json?raw_json=1&limit=100"
    session = requests.Session()
    results = [
        request_one(session, "old-search-json-direct", search_url, args.timeout),
        request_one(session, "old-post-json-direct", post_url, args.timeout),
    ]

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transport": "direct-old-reddit",
        "timeout_seconds": args.timeout,
        "results": results,
        "security_note": "No access token, response body, usernames, or comment text is stored.",
    }
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "direct_old_reddit_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Direct old.reddit.com JSON probe",
        "",
        "| Target | HTTP | Content-Type | Bytes | JSON shape |",
        "|---|---:|---|---:|---|",
    ]
    for item in results:
        lines.append(
            f"| `{item['target']}` | `{item.get('status_code', '')}` | `{item.get('content_type', '')}` | "
            f"{item.get('body_length', '')} | `{json.dumps(item.get('json_shape', item.get('error_type', '')), ensure_ascii=False)}` |"
        )
    lines.extend(
        [
            "",
            "> This probe is direct only. It does not use ScraperAPI and stores no Reddit body or comment text.",
        ]
    )
    (output / "direct_old_reddit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for item in results:
        print(
            f"{item['target']}: status={item.get('status_code')} "
            f"content_type={item.get('content_type', '')} bytes={item.get('body_length', '')}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

