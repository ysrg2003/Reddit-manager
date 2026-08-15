from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


ASYNC_JOBS_URL = "https://async.scraperapi.com/jobs"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit one Reddit search to ScraperAPI Async API and poll until completion."
    )
    parser.add_argument("--queries", default="testdata/corpus_queries.json")
    parser.add_argument("--article-number", type=int, default=1)
    parser.add_argument("--output-dir", default="artifacts/async-probe")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=1800,
        help="Safety bound for the GitHub job; it does not limit ScraperAPI's internal job timeout.",
    )
    return parser.parse_args()


def secret_entries() -> list[tuple[str, str]]:
    raw = (os.getenv("SCRAPER_API_KEYS_JSON") or os.getenv("AI_ROUTER_SCRAPERAPI_KEYS_JSON") or "").strip()
    if not raw:
        raise SystemExit("SCRAPER_API_KEYS_JSON is not available in this GitHub Actions environment.")
    try:
        values: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit("SCRAPER_API_KEYS_JSON must be a JSON array.") from exc
    if not isinstance(values, list):
        raise SystemExit("SCRAPER_API_KEYS_JSON must be a JSON array.")
    entries: list[tuple[str, str]] = []
    for index, item in enumerate(values, 1):
        if isinstance(item, str) and item.strip():
            entries.append((f"scraperapi-{index}", item.strip()))
        elif isinstance(item, dict):
            value = next((item.get(name) for name in ("key", "api_key", "token", "secret", "value") if item.get(name)), None)
            if value:
                entries.append((str(item.get("id") or item.get("name") or f"scraperapi-{index}"), str(value).strip()))
    if not entries:
        raise SystemExit("SCRAPER_API_KEYS_JSON contains no usable key entries.")
    return entries


def build_reddit_search_url(query: str) -> str:
    params = urlencode({"q": query, "limit": 1, "sort": "relevance", "t": "all", "raw_json": 1})
    return f"https://www.reddit.com/search.json?{params}"


def json_from_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def find_listing(value: Any) -> Optional[Dict[str, Any]]:
    value = json_from_value(value)
    if isinstance(value, dict):
        children = ((value.get("data") or {}).get("children") if isinstance(value.get("data"), dict) else None)
        if isinstance(children, list):
            return value
        for child in value.values():
            found = find_listing(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_listing(child)
            if found is not None:
                return found
    return None


def extract_status(response_payload: Any) -> str:
    if isinstance(response_payload, dict):
        return str(response_payload.get("status") or response_payload.get("state") or "").lower()
    return ""


def extract_result_payload(response_payload: Any) -> Any:
    if not isinstance(response_payload, dict):
        return response_payload
    for key in ("response", "result", "data", "body", "content", "html"):
        if key in response_payload:
            candidate = response_payload[key]
            nested = extract_result_payload(candidate)
            if find_listing(nested) is not None:
                return nested
    return response_payload


def safe_result(article: Dict[str, Any], key_id: str, status: str, elapsed: int, payload: Any = None, error: str = "") -> Dict[str, Any]:
    listing = find_listing(extract_result_payload(payload)) if payload is not None else None
    posts = []
    if listing:
        for child in ((listing.get("data") or {}).get("children") or []):
            data = child.get("data") or {}
            permalink = data.get("permalink")
            if permalink:
                posts.append({
                    "title": str(data.get("title") or ""),
                    "subreddit": str(data.get("subreddit") or ""),
                    "url": f"https://www.reddit.com{permalink}",
                })
    result: Dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": utc_now_iso(),
        "provider": "scraperapi_async",
        "article_number": article["article_number"],
        "article_file": article["article_file"],
        "title": article["title"],
        "section": article["section"],
        "query": article["query"],
        "key_id_used": key_id,
        "status": status,
        "elapsed_seconds": elapsed,
        "posts": len(posts),
        "post_urls": [post["url"] for post in posts],
        "post_previews": posts,
        "security_note": "API key values and full Reddit response bodies are intentionally excluded.",
    }
    if error:
        result["error"] = error
    return result


def main() -> int:
    args = parse_args()
    if args.poll_seconds < 5:
        raise SystemExit("--poll-seconds must be at least 5.")
    if args.max_wait_seconds <= 0:
        raise SystemExit("--max-wait-seconds must be positive.")

    payload = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    articles = payload.get("articles") or []
    if not 1 <= args.article_number <= len(articles):
        raise SystemExit(f"article number must be between 1 and {len(articles)}")
    article = articles[args.article_number - 1]
    target_url = build_reddit_search_url(article["query"])
    keys = secret_entries()
    session = requests.Session()
    started = time.monotonic()
    submission_errors: list[str] = []
    selected_key_id = ""
    job: Optional[Dict[str, Any]] = None

    for key_id, secret in keys:
        try:
            response = session.post(
                ASYNC_JOBS_URL,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={
                    "apiKey": secret,
                    "url": target_url,
                    "apiParams": {"render": False, "follow_redirect": True},
                    "meta": {"article_number": article["article_number"]},
                },
                timeout=(10, 30),
            )
            if response.status_code in {401, 403}:
                submission_errors.append(f"{key_id}: HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                submission_errors.append(f"{key_id}: HTTP {response.status_code}")
                break
            candidate = response.json()
            if not isinstance(candidate, dict) or not candidate.get("statusUrl"):
                submission_errors.append(f"{key_id}: submission response had no statusUrl")
                break
            job = candidate
            selected_key_id = key_id
            break
        except requests.RequestException as exc:
            submission_errors.append(f"{key_id}: {type(exc).__name__}")
            break
        except ValueError as exc:
            submission_errors.append(f"{key_id}: {type(exc).__name__}")
            break

    if job is None:
        result = safe_result(article, "none", "submission_failed", int(time.monotonic() - started), error="; ".join(submission_errors))
        write_report(args.output_dir, result)
        return 0

    status_url = str(job["statusUrl"])
    last_payload: Any = job
    last_status = extract_status(job) or "submitted"
    print(f"submitted article={article['article_number']} key={selected_key_id} status={last_status}", flush=True)

    while time.monotonic() - started < args.max_wait_seconds:
        try:
            response = session.get(status_url, headers={"Accept": "application/json"}, timeout=(10, 30))
            response.raise_for_status()
            last_payload = response.json()
            last_status = extract_status(last_payload) or last_status
            elapsed = int(time.monotonic() - started)
            print(f"poll elapsed={elapsed}s status={last_status}", flush=True)
            if last_status in {"success", "succeeded", "completed", "finished", "failed", "error", "cancelled", "canceled"}:
                result = safe_result(article, selected_key_id, last_status, elapsed, payload=last_payload)
                write_report(args.output_dir, result)
                return 0
        except (requests.RequestException, ValueError) as exc:
            print(f"poll transient_error={type(exc).__name__}", flush=True)
        time.sleep(args.poll_seconds)

    result = safe_result(article, selected_key_id, "local_poll_deadline_exceeded", int(time.monotonic() - started), payload=last_payload)
    write_report(args.output_dir, result)
    return 0


def write_report(output_dir: str, result: Dict[str, Any]) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scraperapi_async_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# ScraperAPI Async Single-Article Probe",
        "",
        f"- Article: `{result['article_file']}`",
        f"- Query: `{result['query']}`",
        f"- Key identifier: `{result['key_id_used']}`",
        f"- Status: `{result['status']}`",
        f"- Elapsed seconds: `{result['elapsed_seconds']}`",
        f"- Reddit posts found: `{result['posts']}`",
        "",
        "> The API key value and full Reddit response body are intentionally excluded.",
    ]
    if result.get("error"):
        lines.extend(["", f"- Error class/details: `{result['error']}`"])
    (directory / "scraperapi_async_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
