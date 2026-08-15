from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class QualityAssessment:
    url: str
    score: int
    tier: str
    eligible: bool
    reason: str


# Conservative allowlist for evidence that may enter the Gemini batch.
# Search ranking is never used as a quality signal.
TRUSTED_DOMAINS: dict[str, tuple[int, str]] = {
    "services.google.com": (95, "primary research host"),
    "research.google": (95, "first-party research"),
    "dora.dev": (95, "research program"),
    "csrc.nist.gov": (100, "government security guidance"),
    "survey.stackoverflow.co": (95, "first-party developer survey"),
    "docs.github.com": (95, "official product documentation"),
    "github.com": (85, "official repository; page-specific review required"),
    "genai.owasp.org": (95, "community security project"),
    "owasp.org": (90, "community security project"),
    "hai.stanford.edu": (95, "academic research institute"),
}

BLOCKED_PATTERNS = (
    "login",
    "signin",
    "paywall",
    "captcha",
    "utm_",
)


def _base_domain(host: str) -> str:
    host = host.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def assess_url(url: str) -> QualityAssessment:
    parsed = urlparse(url.strip())
    host = _base_domain(parsed.netloc)
    if parsed.scheme != "https" or not host:
        return QualityAssessment(url, 0, "reject", False, "requires an HTTPS public URL")

    for pattern in BLOCKED_PATTERNS:
        if pattern in url.lower():
            return QualityAssessment(url, 0, "reject", False, f"URL contains blocked access marker: {pattern}")

    domain_match = None
    for domain, entry in TRUSTED_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            domain_match = entry
            break
    if not domain_match:
        return QualityAssessment(url, 0, "reject", False, "domain is not in the conservative evidence allowlist")

    score, reason = domain_match
    tier = "A" if score >= 95 else "B"
    return QualityAssessment(url, score, tier, True, reason)


def rank_urls(urls: list[str], limit: int = 10) -> list[QualityAssessment]:
    assessed = [assess_url(url) for url in urls]
    eligible = [item for item in assessed if item.eligible]
    return sorted(eligible, key=lambda item: (-item.score, item.url))[:limit]
