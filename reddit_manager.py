"""Reddit evidence collector.

The module collects public Reddit JSON data for research workflows. It does not
claim that Reddit content is independently true; every bundle carries source
metadata and an evidence limitation.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

import requests
from requests.adapters import HTTPAdapter


DEFAULT_BASE_URL = "https://www.reddit.com"
DEFAULT_USER_AGENT = "YusufRedditResearch/1.0 (research evidence collector; contact owner before reuse)"
DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGES = 2
DEFAULT_POSTS_PER_PAGE = 10
DEFAULT_COMMENTS_LIMIT = 100
DEFAULT_RETRIES = 3
DEFAULT_DELAY = 1.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return html.unescape(value).strip()


def _safe_permalink(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    if not value.startswith("/") or ".." in value or "?" in value:
        return ""
    return value


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _parse_secret_pool(raw: str, provider: str) -> List[Tuple[str, str]]:
    """Parse ordered secret entries without exposing their values."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        values: Any = json.loads(raw)
    except json.JSONDecodeError:
        values = [raw]
    if isinstance(values, dict):
        values = values.get("keys") or values.get("items") or values.get("entries") or [values]
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        raise ValueError(f"{provider} key pool must be a JSON array or a single key")
    aliases = ("key", "api_key", "token", "secret", "value")
    result: List[Tuple[str, str]] = []
    for index, item in enumerate(values, 1):
        if isinstance(item, str) and item.strip():
            result.append((f"{provider}-{index}", item.strip()))
        elif isinstance(item, dict):
            secret = next((item.get(alias) for alias in aliases if item.get(alias)), None)
            if secret:
                key_id = str(item.get("id") or item.get("name") or f"{provider}-{index}")
                result.append((key_id, str(secret).strip()))
    return result


def _media_urls(data: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    candidate = data.get("url")
    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
        lowered = candidate.lower()
        if any(marker in lowered for marker in (".jpg", ".jpeg", ".png", ".gif", ".webp", "i.redd.it", "imgur.com", "v.redd.it", "gallery")):
            urls.append(candidate)

    text = _clean_text(data.get("selftext") or data.get("body"))
    urls.extend(re.findall(r"https?://[^\s)\]>]+", text))

    metadata = data.get("media_metadata")
    if isinstance(metadata, dict):
        for item in metadata.values():
            if not isinstance(item, dict):
                continue
            size = item.get("s") or {}
            url = size.get("u") or size.get("url")
            if isinstance(url, str):
                urls.append(html.unescape(url))
    return _dedupe(urls)


@dataclass
class CollectorConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    delay: float = DEFAULT_DELAY
    user_agent: str = DEFAULT_USER_AGENT
    verify_tls: bool = True
    access_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    oauth_scope: str = "read"
    scraper_api_key: str = ""
    scraper_api_keys: List[Tuple[str, str]] = field(default_factory=list)
    scraper_api_base: str = "https://api.scraperapi.com"
    brave_api_key: str = ""
    brave_api_base: str = "https://api.search.brave.com/res/v1/web/search"
    direct_enabled: bool = False

    def __post_init__(self) -> None:
        if (self.access_token or (self.client_id and self.client_secret)) and self.base_url == DEFAULT_BASE_URL:
            self.base_url = "https://oauth.reddit.com"
        self.base_url = self.base_url.rstrip("/")
        if not self.scraper_api_keys and self.scraper_api_key:
            self.scraper_api_keys = [("scraperapi-single", self.scraper_api_key)]
        self.scraper_api_base = self.scraper_api_base.rstrip("/")
        self.brave_api_base = self.brave_api_base.rstrip("/")

    @classmethod
    def from_env(cls) -> "CollectorConfig":
        access_token = os.getenv("REDDIT_ACCESS_TOKEN", "").strip()
        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        configured_base = os.getenv("REDDIT_BASE_URL", "").strip()
        base_url = configured_base or ("https://oauth.reddit.com" if (access_token or (client_id and client_secret)) else DEFAULT_BASE_URL)
        return cls(
            base_url=base_url.rstrip("/"),
            timeout=float(os.getenv("REDDIT_TIMEOUT", str(DEFAULT_TIMEOUT))),
            retries=max(0, int(os.getenv("REDDIT_RETRIES", str(DEFAULT_RETRIES)))),
            delay=max(0.0, float(os.getenv("REDDIT_REQUEST_DELAY", str(DEFAULT_DELAY)))),
            user_agent=os.getenv("REDDIT_USER_AGENT", DEFAULT_USER_AGENT),
            verify_tls=os.getenv("REDDIT_VERIFY_TLS", "true").lower() not in {"0", "false", "no"},
            access_token=access_token,
            client_id=client_id,
            client_secret=client_secret,
            oauth_scope=os.getenv("REDDIT_OAUTH_SCOPE", "read").strip() or "read",
            scraper_api_key=os.getenv("SCRAPER_API_KEY", "").strip(),
            scraper_api_keys=_parse_secret_pool(
                os.getenv("SCRAPER_API_KEYS_JSON", "") or os.getenv("AI_ROUTER_SCRAPERAPI_KEYS_JSON", ""),
                "scraperapi",
            ),
            scraper_api_base=os.getenv("SCRAPER_API_BASE", "https://api.scraperapi.com").rstrip("/"),
            brave_api_key=os.getenv("BRAVE_SEARCH_API_KEY", "").strip(),
            brave_api_base=os.getenv("BRAVE_SEARCH_API_BASE", "https://api.search.brave.com/res/v1/web/search").rstrip("/"),
            direct_enabled=os.getenv("REDDIT_DIRECT_ENABLED", "false").lower() in {"1", "true", "yes"},
        )


class RedditFetchError(RuntimeError):
    """Raised when Reddit data cannot be fetched after the configured retries."""


class RedditManager:
    """Fetch and normalize public Reddit JSON without treating it as truth."""

    def __init__(self, session: Optional[requests.Session] = None, config: Optional[CollectorConfig] = None):
        self.config = config or CollectorConfig.from_env()
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
        })
        if self.config.access_token:
            self.session.headers.update({"Authorization": f"Bearer {self.config.access_token}"})
        self.last_warnings: List[str] = []
        self.last_transport: str = "none"

    def _request_scraperapi(self, url: str, params: Dict[str, Any]) -> Any:
        prepared = requests.Request("GET", url, params=params).prepare().url
        errors: List[str] = []
        for key_id, secret in self.config.scraper_api_keys:
            last_error: Optional[Exception] = None
            for attempt in range(self.config.retries + 1):
                try:
                    response = self.session.get(
                        self.config.scraper_api_base,
                        params={"api_key": secret, "url": prepared, "render": "false"},
                        timeout=self.config.timeout,
                        verify=self.config.verify_tls,
                    )
                    status = int(getattr(response, "status_code", 0))
                    if status == 429:
                        raise RedditFetchError("ScraperAPI quota/rate limit reached; key failover is disabled for this response")
                    if status in {401, 403}:
                        raise RedditFetchError(f"ScraperAPI key rejected with HTTP status {status}")
                    if status >= 500:
                        raise RedditFetchError(f"retryable HTTP status {status}")
                    if status >= 400:
                        raise RedditFetchError(f"HTTP status {status}")
                    payload = response.json()
                    self.last_transport = "scraperapi"
                    if self.config.delay and attempt == 0:
                        time.sleep(self.config.delay)
                    return payload
                except (requests.RequestException, ValueError, RedditFetchError) as exc:
                    last_error = exc
                    message = str(exc)
                    if "quota/rate limit" in message:
                        raise RedditFetchError(message) from exc
                    if "key rejected" in message:
                        break
                    if attempt >= self.config.retries:
                        break
                    time.sleep(min(30.0, self.config.delay * (2 ** attempt)))
            errors.append(f"scraperapi/{key_id}: {last_error}")
        raise RedditFetchError("; ".join(errors) or "No ScraperAPI key is configured")

    def _request_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = path if path.startswith("http") else f"{self.config.base_url}/{path.lstrip('/')}"
        request_params = dict(params or {})
        errors: List[str] = []

        # ScraperAPI is an explicit proxy path. Failover is allowed only for
        # rejected/invalid keys; quota exhaustion stops the request.
        if self.config.scraper_api_keys and not self.config.access_token:
            try:
                return self._request_scraperapi(url, request_params)
            except RedditFetchError as exc:
                if "quota/rate limit" in str(exc):
                    raise
                errors.append(str(exc))

        transports: List[Tuple[str, str, Dict[str, Any]]] = []
        if self.config.direct_enabled:
            transports.append(("direct", url, request_params))

        for transport_name, request_url, transport_params in transports:
            last_error: Optional[Exception] = None
            for attempt in range(self.config.retries + 1):
                try:
                    response = self.session.get(
                        request_url,
                        params=transport_params,
                        timeout=self.config.timeout,
                        verify=self.config.verify_tls,
                    )
                    status = int(getattr(response, "status_code", 0))
                    if status == 429 or status >= 500:
                        raise RedditFetchError(f"retryable HTTP status {status}")
                    if status >= 400:
                        raise RedditFetchError(f"HTTP status {status}")
                    payload = response.json()
                    self.last_transport = transport_name
                    if self.config.delay and attempt == 0:
                        time.sleep(self.config.delay)
                    return payload
                except (requests.RequestException, ValueError, RedditFetchError) as exc:
                    last_error = exc
                    if attempt >= self.config.retries:
                        break
                    time.sleep(min(30.0, self.config.delay * (2 ** attempt)))
            errors.append(f"{transport_name}: {last_error}")

        raise RedditFetchError(f"Could not fetch {url}; {' | '.join(errors)}")

    def _parse_comment_children(self, children: Sequence[Dict[str, Any]], permalink: str, depth: int = 0) -> List[Dict[str, Any]]:
        comments: List[Dict[str, Any]] = []
        for child in children:
            if not isinstance(child, dict) or child.get("kind") != "t1":
                continue
            data = child.get("data") or {}
            body = _clean_text(data.get("body"))
            if not body or body in {"[deleted]", "[removed]"}:
                continue
            comment_id = _clean_text(data.get("id"))
            nested = []
            replies = data.get("replies")
            if isinstance(replies, dict):
                nested = self._parse_comment_children(
                    (replies.get("data") or {}).get("children", []), permalink, depth + 1
                )
            comments.append({
                "evidence_type": "user_report",
                "comment_id": comment_id,
                "author": data.get("author"),
                "body": body,
                "score": int(data.get("score") or 0),
                "depth": depth,
                "url": f"{self.config.base_url}{permalink}{comment_id}" if comment_id else f"{self.config.base_url}{permalink}",
                "media": _media_urls(data),
                "replies": nested,
            })
        return comments

    def _parse_post(self, post_data: Dict[str, Any], comments_data: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        permalink = _safe_permalink(post_data.get("permalink"))
        comments = self._parse_comment_children(comments_data, permalink)
        return {
            "evidence_type": "community_signal",
            "post_id": post_data.get("id"),
            "subreddit": post_data.get("subreddit"),
            "title": _clean_text(post_data.get("title")),
            "text": _clean_text(post_data.get("selftext")),
            "author": post_data.get("author"),
            "score": int(post_data.get("score") or 0),
            "num_comments": int(post_data.get("num_comments") or 0),
            "created_utc": post_data.get("created_utc"),
            "url": f"{self.config.base_url}{permalink}" if permalink else post_data.get("url"),
            "permalink": permalink,
            "media": _media_urls(post_data),
            "comments": comments,
            "verification_status": "unverified_user_generated_content",
        }

    def fetch_post(self, permalink: str, comments_limit: int = DEFAULT_COMMENTS_LIMIT) -> Dict[str, Any]:
        safe = _safe_permalink(permalink)
        if not safe:
            raise ValueError("permalink must be a Reddit path beginning with '/'")
        payload = self._request_json(f"{safe}.json", {"limit": comments_limit, "raw_json": 1})
        if not isinstance(payload, list) or len(payload) < 2:
            raise RedditFetchError(f"Unexpected post response for {safe}")
        post_children = ((payload[0].get("data") or {}).get("children") or [])
        if not post_children:
            raise RedditFetchError(f"Post not found for {safe}")
        post_data = post_children[0].get("data") or {}
        comments = ((payload[1].get("data") or {}).get("children") or [])
        return self._parse_post(post_data, comments)

    def search_listing(
        self,
        query: str,
        posts_per_page: int = DEFAULT_POSTS_PER_PAGE,
        sort: str = "relevance",
        time_window: str = "all",
    ) -> Dict[str, Any]:
        """Fetch one Reddit search listing without fetching post detail pages."""
        query = _clean_text(query)
        if not query:
            raise ValueError("query must not be empty")
        params = {
            "q": query,
            "limit": max(1, min(int(posts_per_page), 100)),
            "sort": sort,
            "t": time_window,
            "raw_json": 1,
        }
        payload = self._request_json("/search.json", params)
        children = ((payload or {}).get("data") or {}).get("children") or []
        posts: List[Dict[str, Any]] = []
        for child in children:
            data = child.get("data") or {}
            permalink = _safe_permalink(data.get("permalink"))
            if not permalink:
                continue
            posts.append({
                "evidence_type": "community_signal_listing",
                "post_id": data.get("id"),
                "subreddit": _clean_text(data.get("subreddit")),
                "title": _clean_text(data.get("title")),
                "text": _clean_text(data.get("selftext")),
                "author": _clean_text(data.get("author")),
                "score": data.get("score"),
                "num_comments": data.get("num_comments"),
                "url": f"https://www.reddit.com{permalink}",
                "permalink": permalink,
                "comments": [],
                "media": [],
                "verification_status": "unverified_user_generated_content",
            })
        return {
            "schema_version": "1.1",
            "query": query,
            "retrieved_at": utc_now_iso(),
            "source": "Reddit search listing via ScraperAPI",
            "transport": self.last_transport,
            "evidence_policy": "Search listings are user-generated signals and remain unverified until the source page and important claims are independently checked.",
            "parameters": params,
            "posts": posts,
            "warnings": [],
        }

    def search(
        self,
        query: str,
        pages: int = DEFAULT_PAGES,
        posts_per_page: int = DEFAULT_POSTS_PER_PAGE,
        comments_limit: int = DEFAULT_COMMENTS_LIMIT,
        sort: str = "relevance",
        time_window: str = "all",
    ) -> Dict[str, Any]:
        query = _clean_text(query)
        if not query:
            raise ValueError("query must not be empty")
        pages = max(1, min(int(pages), 20))
        posts_per_page = max(1, min(int(posts_per_page), 100))
        comments_limit = max(0, min(int(comments_limit), 500))
        posts: List[Dict[str, Any]] = []
        after: Optional[str] = None
        warnings: List[str] = []
        if not self.config.direct_enabled and not self.config.scraper_api_keys:
            return {
                "schema_version": "1.1",
                "query": query,
                "retrieved_at": utc_now_iso(),
                "source": "Reddit public JSON endpoints",
                "transport": "disabled",
                "evidence_policy": "Reddit posts and comments are user-generated signals and remain unverified until independently checked.",
                "parameters": {"pages": pages, "posts_per_page": posts_per_page, "comments_limit": comments_limit, "sort": sort, "time_window": time_window},
                "posts": [],
                "warnings": ["Direct Reddit transport is disabled. Use an explicitly permitted fallback provider or set REDDIT_DIRECT_ENABLED=true only when direct access is authorized and available."],
            }

        for _ in range(pages):
            params: Dict[str, Any] = {
                "q": query,
                "limit": posts_per_page,
                "sort": sort,
                "t": time_window,
                "raw_json": 1,
            }
            if after:
                params["after"] = after
            try:
                payload = self._request_json("/search.json", params)
            except RedditFetchError as exc:
                warnings.append(str(exc))
                break
            listing = (payload or {}).get("data") or {}
            children = listing.get("children") or []
            after = listing.get("after")
            for child in children:
                data = child.get("data") or {}
                permalink = _safe_permalink(data.get("permalink"))
                if not permalink:
                    continue
                try:
                    posts.append(self.fetch_post(permalink, comments_limit=comments_limit))
                except RedditFetchError as exc:
                    warnings.append(f"Could not fetch {permalink}: {exc}")
            if not after:
                break

        unique: Dict[str, Dict[str, Any]] = {}
        for post in posts:
            key = post.get("post_id") or post.get("url")
            if key:
                unique[str(key)] = post
        result = {
            "schema_version": "1.0",
            "query": query,
            "retrieved_at": utc_now_iso(),
            "source": "Reddit public JSON endpoints",
            "transport": self.last_transport,
            "evidence_policy": "Reddit posts and comments are user-generated signals and remain unverified until independently checked.",
            "parameters": {
                "pages": pages,
                "posts_per_page": posts_per_page,
                "comments_limit": comments_limit,
                "sort": sort,
                "time_window": time_window,
            },
            "posts": list(unique.values()),
            "warnings": warnings,
        }
        return result

    def search_via_brave(
        self,
        query: str,
        count: int = 10,
        country: str = "us",
        search_lang: str = "en",
    ) -> Dict[str, Any]:
        query = _clean_text(query)
        if not query:
            raise ValueError("query must not be empty")
        if not self.config.brave_api_key:
            return {
                "schema_version": "1.1",
                "query": query,
                "retrieved_at": utc_now_iso(),
                "source": "Brave Search API",
                "transport": "brave_search_api_unconfigured",
                "evidence_policy": "Search snippets are discovery signals and remain unverified until the underlying source is independently checked.",
                "posts": [],
                "warnings": ["BRAVE_SEARCH_API_KEY is not configured."],
            }
        response = self.session.get(
            self.config.brave_api_base,
            headers={"Accept": "application/json", "X-Subscription-Token": self.config.brave_api_key},
            params={"q": query, "count": max(1, min(int(count), 20)), "country": country, "search_lang": search_lang},
            timeout=self.config.timeout,
            verify=self.config.verify_tls,
        )
        if response.status_code >= 400:
            raise RedditFetchError(f"Brave Search API HTTP status {response.status_code}")
        payload = response.json()
        results = ((payload or {}).get("web") or {}).get("results") or []
        posts: List[Dict[str, Any]] = []
        for item in results:
            url = item.get("url") or ""
            if "reddit.com" not in url.lower():
                continue
            posts.append({
                "evidence_type": "community_search_snippet",
                "title": _clean_text(item.get("title")),
                "text": _clean_text(item.get("description")),
                "url": url,
                "score": None,
                "num_comments": None,
                "comments": [],
                "media": [],
                "verification_status": "unverified_search_snippet",
                "provider": "Brave Search API",
            })
        return {
            "schema_version": "1.1",
            "query": query,
            "retrieved_at": utc_now_iso(),
            "source": "Brave Search API",
            "transport": "brave_search_api",
            "evidence_policy": "Search snippets are discovery signals and remain unverified until the underlying source is independently checked.",
            "parameters": {"count": count, "country": country, "search_lang": search_lang},
            "posts": posts,
            "warnings": [] if posts else ["Brave returned no Reddit URLs for this query."],
        }

    def search_with_fallback(self, query: str, provider: str = "scraperapi", **kwargs: Any) -> Dict[str, Any]:
        provider = provider.lower().strip()
        if provider not in {"auto", "reddit", "scraperapi", "brave"}:
            raise ValueError("provider must be auto, reddit, scraperapi, or brave")
        if provider == "brave":
            return self.search_via_brave(query, count=kwargs.get("posts_per_page", DEFAULT_POSTS_PER_PAGE))
        if provider in {"reddit", "scraperapi"}:
            return self.search(query, **kwargs)

        if self.config.scraper_api_keys and not self.config.access_token:
            scraper = self.search(query, **kwargs)
            if scraper.get("posts") or not self.config.brave_api_key:
                return scraper
        if self.config.direct_enabled:
            direct = self.search(query, **kwargs)
            if direct.get("posts") or not direct.get("warnings"):
                return direct
        if self.config.brave_api_key:
            return self.search_via_brave(query, count=kwargs.get("posts_per_page", DEFAULT_POSTS_PER_PAGE))
        disabled = self.search(query, **kwargs)
        disabled["warnings"].append("No permitted fallback provider is configured. Configure BRAVE_SEARCH_API_KEY for free-credit search or use an authorized Reddit API route.")
        return disabled


def _flatten_comments(comments: Sequence[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for comment in comments:
        yield comment
        yield from _flatten_comments(comment.get("replies") or [])


def generate_writer_brief(bundle: Dict[str, Any]) -> str:
    """Create a cautious Markdown brief that preserves provenance and uncertainty."""
    if not bundle or not bundle.get("posts"):
        return ""
    lines = [
        "--- REDDIT EVIDENCE FILE ---",
        f"Query: {bundle.get('query', '')}",
        f"Retrieved: {bundle.get('retrieved_at', '')}",
        "Evidence status: UNVERIFIED USER-GENERATED SIGNALS",
        "Use: Research leads only. Independently verify factual claims before publication.",
        "",
    ]
    for index, post in enumerate(bundle.get("posts", []), 1):
        lines.extend([
            f"## THREAD {index}: {post.get('title', 'Untitled')}",
            f"Subreddit: r/{post.get('subreddit', '')}",
            f"URL: {post.get('url', '')}",
            f"Score: {post.get('score', 0)} | Comments: {post.get('num_comments', 0)}",
            f"Post evidence type: {post.get('evidence_type', 'community_signal')}",
        ])
        text = post.get("text") or ""
        if text:
            lines.append(f"Post text: {text[:2000]}")
        comments = sorted(
            list(_flatten_comments(post.get("comments") or [])),
            key=lambda item: item.get("score", 0),
            reverse=True,
        )[:10]
        if comments:
            lines.append("Top community responses:")
            for comment in comments:
                body = (comment.get("body") or "").replace("\n", " ")[:800]
                lines.append(f"- u/{comment.get('author', 'unknown')} (score {comment.get('score', 0)}): {body}")
                lines.append(f"  Source: {comment.get('url', '')}")
        lines.append("")
    if bundle.get("warnings"):
        lines.append("## Collection warnings")
        lines.extend(f"- {warning}" for warning in bundle["warnings"])
    return "\n".join(lines).strip() + "\n"


def get_community_intel(long_keyword: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Backward-compatible adapter returning (brief, media_assets)."""
    bundle = RedditManager().search_with_fallback(long_keyword, provider=os.getenv("REDDIT_PROVIDER", "scraperapi"))
    brief = generate_writer_brief(bundle)
    media_assets: List[Dict[str, Any]] = []
    for post in bundle.get("posts", []):
        for media_url in post.get("media", []):
            media_assets.append({
                "type": "media",
                "url": media_url,
                "source": post.get("url"),
                "evidence_status": "unverified_user_generated_content",
            })
        for comment in _flatten_comments(post.get("comments") or []):
            for media_url in comment.get("media", []):
                media_assets.append({
                    "type": "media",
                    "url": media_url,
                    "source": comment.get("url"),
                    "evidence_status": "unverified_user_generated_content",
                })
    return brief, media_assets


def bundle_to_json(bundle: Dict[str, Any]) -> str:
    return json.dumps(bundle, ensure_ascii=False, indent=2)
