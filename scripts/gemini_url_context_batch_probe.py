from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from source_quality import assess_url, rank_urls


DEFAULT_INPUT = "testdata/gemini_quality_batch.json"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


def load_entries(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("input must be a JSON list")
    entries: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            entries.append({"url": item})
        elif isinstance(item, dict) and isinstance(item.get("url"), str):
            entries.append(item)
    return entries


def build_prompt(entries: list[dict[str, Any]]) -> str:
    url_lines = "\n".join(f"{index}. {item['url']}" for index, item in enumerate(entries, 1))
    return f"""Analyze these public webpages as a research-evidence batch for an English blog about AI-assisted building, automation, debugging, and systems thinking.

URLs:
{url_lines}

Return one concise JSON object with exactly these keys:
- batch_status
- sources: an array with one object per URL, preserving input order and containing source_url, access_status, page_title, source_type, publisher_or_author, concise_summary, factual_claims, opinions_or_experiences, relevance, citations, limitations, confidence
- cross_source_patterns
- contradictions_or_quality_warnings
- editorial_use_rules

Do not invent missing text, authors, facts, comments, or citations. If a page is blocked, incomplete, inaccessible, or only exposes metadata, state that explicitly in access_status and limitations. Distinguish primary evidence, institutional guidance, product documentation, and anecdotal opinion. Do not treat a source's search ranking as evidence of quality. Preserve each source URL and cite only content actually retrieved from that URL. The output is research support, not final publication copy.
""".strip()


def write_report(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gemini_url_context_batch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=os.getenv("GEMINI_URLS_FILE", DEFAULT_INPUT))
    parser.add_argument("--output-dir", default=os.getenv("GEMINI_OUTPUT_DIR", "artifacts/gemini-url-context-batch"))
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    try:
        entries = load_entries(Path(args.input))
    except Exception as exc:
        write_report(output_dir, {"status": "invalid_input", "error": str(exc)[:500], "secret_value_saved": False})
        return 2

    assessments = [assess_url(item["url"]) for item in entries]
    selected = rank_urls([item["url"] for item in entries], limit=args.limit)
    selected_urls = {item.url for item in selected}
    selected_entries = [item for item in entries if item["url"] in selected_urls]
    excluded = [
        {"url": item.url, "score": item.score, "tier": item.tier, "reason": item.reason}
        for item in assessments
        if item.url not in selected_urls
    ]

    base_report = {
        "status": "missing_key" if not api_key else "prepared",
        "input_count": len(entries),
        "selected_count": len(selected_entries),
        "selected_urls": [item["url"] for item in selected_entries],
        "quality_assessments": [item.__dict__ for item in assessments],
        "excluded_urls": excluded,
        "secret_value_saved": False,
    }
    if not api_key:
        write_report(output_dir, base_report)
        print(json.dumps({"status": "missing_key", "selected_count": len(selected_entries)}))
        return 2
    if not selected_entries:
        base_report["status"] = "no_eligible_urls"
        write_report(output_dir, base_report)
        return 2

    payload = {
        "model": "gemini-3.6-flash",
        "input": build_prompt(selected_entries),
        "tools": [{"type": "url_context"}],
    }
    try:
        response = requests.post(
            ENDPOINT,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"raw_response_prefix": response.text[:1000]}
        base_report.update({
            "status": "ok" if response.ok else "api_error",
            "http_status": response.status_code,
            "response": data,
        })
    except Exception as exc:
        base_report.update({
            "status": "request_error",
            "http_status": None,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        })
    write_report(output_dir, base_report)
    print(json.dumps({
        "status": base_report["status"],
        "http_status": base_report.get("http_status"),
        "selected_count": len(selected_entries),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
