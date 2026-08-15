from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests


DEFAULT_URL = "https://www.linkedin.com/posts/simonlunnprofile_turbocoding-ai-nocode-activity-7457934952937013249-VggA"


def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    target_url = os.getenv("GEMINI_TEST_URL", DEFAULT_URL).strip()
    output_dir = Path(os.getenv("GEMINI_OUTPUT_DIR", "artifacts/gemini-url-context"))
    output_dir.mkdir(parents=True, exist_ok=True)
    if not api_key:
        report = {"status": "missing_key", "secret_value_saved": False}
        (output_dir / "gemini_url_context_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Gemini API key is not available")
        return 2

    prompt = f"""
Analyze the public webpage at this URL for a research evidence workflow: {target_url}

Return a concise JSON object with exactly these keys:
- source_url
- access_status
- page_title
- post_or_article_text
- visible_comments_or_replies
- factual_claims
- opinions_or_experiences
- relevance_to_ai_assisted_building_and_automation
- limitations

Do not invent missing text. If the page requires login, is blocked, or exposes only partial content, say so explicitly in access_status and limitations. Treat all extracted member-generated content as unverified research leads.
""".strip()
    payload = {
        "model": "gemini-3.6-flash",
        "input": prompt,
        "tools": [{"type": "url_context"}],
    }
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        data = response.json()
    except Exception as exc:
        report = {
            "status": "request_error",
            "http_status": None,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "secret_value_saved": False,
        }
        (output_dir / "gemini_url_context_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["error"])
        return 1

    report = {
        "status": "ok" if response.ok else "api_error",
        "http_status": response.status_code,
        "target_url": target_url,
        "response": data,
        "secret_value_saved": False,
    }
    (output_dir / "gemini_url_context_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "http_status": response.status_code, "target_url": target_url}, ensure_ascii=False))
    # Preserve the API error body in the artifact for diagnosis; never print or save the API key.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
