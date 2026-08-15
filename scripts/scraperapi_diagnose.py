from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import urlencode

import requests


DEFAULT_BASE = "https://api.scraperapi.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose ScraperAPI key, API health, and Reddit target compatibility")
    parser.add_argument("--output-dir", default="artifacts/scraperapi-diagnosis")
    parser.add_argument("--timeout", type=float, default=70.0)
    return parser.parse_args()


def parse_first_key() -> tuple[str, str]:
    raw = (os.getenv("SCRAPER_API_KEYS_JSON") or os.getenv("AI_ROUTER_SCRAPERAPI_KEYS_JSON") or "").strip()
    if not raw:
        raise SystemExit("SCRAPER_API_KEYS_JSON is not available.")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit("SCRAPER_API_KEYS_JSON must be valid JSON.") from exc
    if not isinstance(values, list):
        raise SystemExit("SCRAPER_API_KEYS_JSON must be a JSON array.")
    for index, item in enumerate(values, 1):
        if isinstance(item, str) and item.strip():
            return f"scraperapi-{index}", item.strip()
        if isinstance(item, dict):
            for field in ("key", "api_key", "token", "secret", "value"):
                value = item.get(field)
                if value:
                    return str(item.get("id") or item.get("name") or f"scraperapi-{index}"), str(value).strip()
    raise SystemExit("SCRAPER_API_KEYS_JSON contains no usable key.")


def target_urls() -> list[tuple[str, str]]:
    query = urlencode({"q": "vibe coding trap why building assisted", "limit": 1, "sort": "relevance", "t": "all", "raw_json": 1})
    html_query = urlencode({"q": "vibe coding trap why building assisted", "sort": "relevance"})
    post_url = "https://www.reddit.com/r/AI_Agents/comments/1vkb9yy/the_biggest_trap_ive_hit_doing_vibe_coding_as/"
    return [
        ("provider-health", "https://example.com"),
        ("reddit-json", f"https://www.reddit.com/search.json?{query}"),
        ("reddit-html", f"https://www.reddit.com/search/?{html_query}"),
        ("reddit-html-render", f"https://www.reddit.com/search/?{html_query}"),
        ("reddit-post-html", post_url),
        ("reddit-post-autoparse", post_url),
    ]


class _HTMLStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags = Counter()
        self.samples = []
        self.capture_depth = 0
        self.text_parts = []
        self.current_link = None
        self.link_samples = []

    def handle_starttag(self, tag, attrs):
        self.tags[tag.lower()] += 1
        if tag.lower() == "a":
            href = next((value for name, value in attrs if name == "href" and value), "")
            self.current_link = {"path": urlparse(href).path[:300] if href else "", "text": ""}
        if len(self.samples) < 80:
            keys = sorted({name for name, _ in attrs})
            href = next((value for name, value in attrs if name == "href" and value), "")
            if href:
                parsed = urlparse(href)
                href = parsed.path[:200]
            self.samples.append({"tag": tag.lower(), "attribute_names": keys, "path": href})
        if tag.lower() in {"script", "style"}:
            self.capture_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current_link is not None:
            if self.current_link.get("path") and len(self.link_samples) < 120:
                self.link_samples.append({
                    "path": self.current_link["path"],
                    "text": " ".join(self.current_link.get("text", "").split())[:240],
                })
            self.current_link = None
        if tag.lower() in {"script", "style"} and self.capture_depth:
            self.capture_depth -= 1

    def handle_data(self, data):
        if self.current_link is not None and not self.capture_depth:
            self.current_link["text"] += " " + data
        if not self.capture_depth:
            text = " ".join(data.split())
            if text and len(self.text_parts) < 20:
                self.text_parts.append(text[:120])


def summarize_html(content: str) -> dict:
    parser = _HTMLStructureParser()
    parser.feed(content or "")
    parser.close()
    return {
        "tag_counts": dict(parser.tags.most_common(30)),
        "sample_elements": parser.samples,
        "link_samples": parser.link_samples,
        "text_samples": parser.text_parts,
    }


def classify(status: int, body_length: int) -> str:
    if status in {200, 404}:
        return "provider_response"
    if status in {401, 403}:
        return "key_or_access_rejected"
    if status == 429:
        return "quota_or_concurrency_limited"
    if status == 500:
        return "target_fetch_failed_or_provider_retry_exhausted"
    if status >= 400:
        return "provider_error"
    return "unexpected"


def main() -> int:
    args = parse_args()
    key_id, secret = parse_first_key()
    base = os.getenv("SCRAPER_API_BASE", DEFAULT_BASE).rstrip("/")
    session = requests.Session()
    results = []
    for label, target in target_urls():
        started = time.monotonic()
        try:
            response = session.get(
                base,
                params={
                    "api_key": secret,
                    "url": target,
                    "render": "true" if label == "reddit-html-render" else "false",
                    "autoparse": "true" if label == "reddit-post-autoparse" else "false",
                },
                timeout=args.timeout,
                verify=True,
            )
            elapsed = round(time.monotonic() - started, 3)
            result = {
                "target": label,
                "status_code": response.status_code,
                "classification": classify(response.status_code, len(response.content)),
                "elapsed_seconds": elapsed,
                "body_length": len(response.content),
                "content_type": response.headers.get("content-type", ""),
            }
            if label in {"reddit-html", "reddit-html-render", "reddit-post-html"} and response.status_code == 200:
                result["html_structure"] = summarize_html(response.text)
            if label == "reddit-post-autoparse" and response.status_code == 200:
                try:
                    parsed = response.json()
                    result["json_type"] = type(parsed).__name__
                    result["json_keys"] = sorted(parsed.keys()) if isinstance(parsed, dict) else []
                    if isinstance(parsed, dict):
                        result["json_list_lengths"] = {
                            key: len(value) for key, value in parsed.items() if isinstance(value, list)
                        }
                except ValueError:
                    result["json_type"] = "not_json"
            results.append(result)
            print(f"{label}: status={response.status_code} elapsed={elapsed}s bytes={len(response.content)}", flush=True)
            if response.status_code == 429:
                break
        except requests.RequestException as exc:
            elapsed = round(time.monotonic() - started, 3)
            results.append({
                "target": label,
                "status_code": None,
                "classification": "client_or_network_error",
                "elapsed_seconds": elapsed,
                "error_type": type(exc).__name__,
            })
            print(f"{label}: error={type(exc).__name__} elapsed={elapsed}s", flush=True)
            break

    report = {
        "schema_version": "1.0",
        "provider": "scraperapi",
        "key_id_used": key_id,
        "timeout_seconds": args.timeout,
        "results": results,
        "security_note": "The API key value and response bodies are intentionally excluded.",
    }
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "scraperapi_diagnosis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# ScraperAPI Diagnosis",
        "",
        f"- Key identifier used: `{key_id}`",
        f"- Timeout per request: `{args.timeout}` seconds",
        "",
        "| Target | HTTP status | Classification | Seconds | Bytes |",
        "|---|---:|---|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| `{result['target']}` | `{result.get('status_code', '')}` | `{result['classification']}` | `{result['elapsed_seconds']}` | `{result.get('body_length', '')}` |"
        )
    lines.extend(["", "> API key values and response bodies are intentionally excluded."])
    (output / "scraperapi_diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
