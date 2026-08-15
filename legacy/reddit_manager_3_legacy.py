# reddit_manager.py
# ==============================================================================
# Reddit Manager - Robust Reddit evidence gatherer (ScraperAPI-enabled)
# - Sanitizes queries for reddit search
# - Supports ScraperAPI proxy (optional, via SCRAPER_API_KEY)
# - Logs JSON snippets for debugging when no results
# - Returns same shape expected by main.py: (text_context, media_assets)
# ==============================================================================

import os
import time
import re
import json
import urllib.parse
from typing import List, Dict, Any, Optional

import requests
import urllib3

# Try to import project's config.log and USER_AGENTS; fallback to simple logger
try:
    from config import log, USER_AGENTS
except Exception:
    def log(msg: str):
        print(msg)
    USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117 Safari/537.36"]

# suppress insecure warnings if verify=False is used anywhere
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------------
# CONFIGURABLE / ENV VARIABLES
# -----------------------------
PAGES_TO_FETCH = int(os.getenv("REDDIT_PAGES_TO_FETCH", "2"))
POSTS_PER_PAGE = int(os.getenv("REDDIT_POSTS_PER_PAGE", "3"))
COMMENTS_LIMIT = int(os.getenv("REDDIT_COMMENTS_LIMIT", "100"))
REQUEST_DELAY = float(os.getenv("REDDIT_REQUEST_DELAY", "1.0"))
USE_SCRAPERAPI = os.getenv("USE_SCRAPERAPI_IF_AVAILABLE", "true").lower() in ("1", "true", "yes")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "").strip()
# Which reddit host to fetch (old or www). Some proxies behave differently for each.
BASE_FETCH = os.getenv("REDDIT_BASE_FETCH", "https://old.reddit.com").rstrip("/")
OUTPUT_BASE = os.getenv("REDDIT_OUTPUT_BASE", "https://www.reddit.com").rstrip("/")
# default time window for reddit search (all | year | month | week | day)
DEFAULT_TIME_WINDOW = os.getenv("REDDIT_TIME_WINDOW", "all")

# Helpers
def _choose_user_agent() -> str:
    try:
        if isinstance(USER_AGENTS, list) and USER_AGENTS:
            return USER_AGENTS[0]
    except Exception:
        pass
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117 Safari/537.36"

class RedditManager:
    def __init__(self, session: Optional[requests.Session] = None, user_agent: Optional[str] = None):
        self.session = session or requests.Session()
        ua = user_agent or _choose_user_agent()
        self.session.headers.update({"User-Agent": ua, "Accept": "application/json"})
        # Use ScraperAPI only if configured and key present
        self.use_scraper = USE_SCRAPERAPI and bool(SCRAPER_API_KEY)
        self.scraper_key = SCRAPER_API_KEY if self.use_scraper else None

    def _get_reddit_json_url(self, url: str) -> str:
        if ".json" not in url:
            if "?" in url:
                base, params = url.split("?", 1)
                return f"{base.rstrip('/')}.json?{params}"
            return f"{url.rstrip('/')}.json"
        return url

    def _fetch_raw(self, url: str, timeout: int = 30) -> Optional[requests.Response]:
        """
        Try in order:
          1) ScraperAPI proxy (if enabled)
          2) Direct request to BASE_FETCH
        Returns requests.Response or None.
        """
        # prefer proxy if enabled
        if self.use_scraper and self.scraper_key:
            try:
                encoded = urllib.parse.quote(url, safe="")
                # try https first (some environments prefer http)
                proxy_url = f"https://api.scraperapi.com?api_key={self.scraper_key}&url={encoded}&render=true"
                log(f" [RedditManager] Attempting ScraperAPI proxy for {url[:160]}")
                resp = self.session.get(proxy_url, timeout=timeout, verify=False)
                log(f" [RedditManager] ScraperAPI status: {resp.status_code} content-type: {resp.headers.get('Content-Type')}")
                if resp.status_code == 200:
                    return resp
                else:
                    log(f" [RedditManager] ScraperAPI returned {resp.status_code}. Falling back to direct.")
            except Exception as e:
                log(f" [RedditManager] ScraperAPI request failed: {e}. Falling back to direct.")

            # second attempt: try http proxy endpoint (sometimes required)
            try:
                encoded = urllib.parse.quote(url, safe="")
                proxy_url = f"http://api.scraperapi.com?api_key={self.scraper_key}&url={encoded}"
                log(f" [RedditManager] Attempting ScraperAPI (http) for {url[:160]}")
                resp = self.session.get(proxy_url, timeout=timeout, verify=False)
                log(f" [RedditManager] ScraperAPI(http) status: {resp.status_code} content-type: {resp.headers.get('Content-Type')}")
                if resp.status_code == 200:
                    return resp
                else:
                    log(f" [RedditManager] ScraperAPI(http) returned {resp.status_code}.")
            except Exception as e:
                log(f" [RedditManager] ScraperAPI(http) request failed: {e}.")
            # if proxy fails, fall through to direct below

        # Direct fetch fallback
        try:
            log(f" [RedditManager] Direct fetch: {url[:160]}")
            resp = self.session.get(url, timeout=timeout, verify=False)
            log(f" [RedditManager] Direct fetch status: {resp.status_code} content-type: {resp.headers.get('Content-Type')}")
            if resp.status_code == 200:
                return resp
            else:
                log(f" [RedditManager] Direct fetch returned {resp.status_code}.")
                return None
        except Exception as e:
            log(f" [RedditManager] Direct fetch error: {e}")
            return None

    def _get_json(self, url: str) -> Optional[Any]:
        resp = self._fetch_raw(url)
        if not resp:
            return None
        text = resp.text or ""
        ct = (resp.headers.get("Content-Type") or "").lower()
        # If content-type indicates JSON or the body looks JSON-ish, attempt to parse
        if "application/json" in ct or text.strip().startswith(("{", "[")):
            try:
                return resp.json()
            except Exception as e:
                log(f" [RedditManager] JSON parse error: {e}")
                # log snippet for debugging
                log(f" [RedditManager] Response snippet: {text[:1000]}")
                return None
        else:
            # sometimes proxy returns HTML wrapper even for .json endpoints
            log(f" [RedditManager] Non-JSON response (content-type={ct}). Snippet: {text[:1000]}")
            return None

    def _extract_media(self, data: Dict[str, Any]) -> List[str]:
        media: List[str] = []
        url = (data.get("url") or "") or ""
        if isinstance(url, str) and any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", "v.redd.it", "imgur.com", "i.redd.it", "gallery"]):
            media.append(url)
        text = (data.get("selftext") or data.get("body") or "") or ""
        found = re.findall(r'(https?://[^\s)\]]+\.(?:jpg|jpeg|png|gif|mp4))', text, re.IGNORECASE)
        media.extend(found)
        # media_metadata handling
        if isinstance(data.get("media_metadata"), dict):
            for item in data["media_metadata"].values():
                s = item.get("s") or {}
                u = s.get("u") or s.get("url")
                if u:
                    media.append(u.replace("&amp;", "&"))
        # dedupe while preserving order
        seen = set()
        out = []
        for m in media:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def _parse_comments(self, children: List[Dict[str, Any]], post_permalink: str) -> List[Dict[str, Any]]:
        parsed: List[Dict[str, Any]] = []
        if not children:
            return parsed
        for child in children:
            if child.get("kind") != "t1":
                continue
            d = child.get("data") or {}
            author = d.get("author")
            body = d.get("body") or ""
            if not body or body in ("[deleted]", "[removed]"):
                continue
            cid = d.get("id")
            # build direct comment link on www.reddit.com (post_permalink includes trailing slash)
            comment_link = f"{OUTPUT_BASE}{post_permalink}{cid}"
            # nested replies
            replies: List[Dict[str, Any]] = []
            r = d.get("replies")
            if isinstance(r, dict):
                nested = r.get("data", {}).get("children", [])
                replies = self._parse_comments(nested, post_permalink)
            parsed.append({
                "comment_id": cid,
                "author": author,
                "body": body,
                "score": d.get("score", 0),
                "url": comment_link,
                "media": self._extract_media(d),
                "replies": replies
            })
        return parsed

    def _fetch_post_with_comments(self, permalink: str, comments_limit: int = COMMENTS_LIMIT) -> Optional[Dict[str, Any]]:
        url = f"{BASE_FETCH}{permalink}.json?limit={comments_limit}"
        j = self._get_json(url)
        if not j or not isinstance(j, list) or len(j) < 2:
            log(f" [RedditManager] No valid JSON for post {permalink}")
            return None
        try:
            post_data = j[0]["data"]["children"][0]["data"]
            comments_children = j[1]["data"].get("children", [])
            post_link = f"{OUTPUT_BASE}{permalink}"
            post = {
                "title": post_data.get("title"),
                "text": post_data.get("selftext") or "",
                "author": post_data.get("author"),
                "score": post_data.get("score", 0),
                "url": post_link,
                "media": self._extract_media(post_data)
            }
            comments = self._parse_comments(comments_children, permalink)
            return {"post": post, "comments": comments}
        except Exception as e:
            log(f" [RedditManager] parse post error: {e}")
            return None

    def search(self, query: str, pages: int = PAGES_TO_FETCH, posts_per_page: int = POSTS_PER_PAGE, comments_limit: int = COMMENTS_LIMIT, delay: float = REQUEST_DELAY) -> Dict[str, Any]:
        """
        Search reddit using the graduated query provided by ai_strategy.
        Returns dict: {"query": original_query, "posts": [...]}
        """
        results: Dict[str, Any] = {"query": query, "posts": []}
        after = None

        # --- sanitize query for reddit search:
        # remove "site:..." clauses because they're meant for Google and can break reddit search
        q = re.sub(r'\bsite:\S+\b', '', query, flags=re.IGNORECASE).strip()
        # remove double quotes to broaden matching (reddit search handles quoted phrases poorly)
        q = q.replace('"', '').strip()
        # fallback to default time window
        time_window = DEFAULT_TIME_WINDOW or "all"

        for page in range(max(1, pages)):
            log(f" [RedditManager] Fetching search page {page+1} for '{query}' (sanitized: '{q}')")
            search_url = f"{BASE_FETCH}/search.json?q={urllib.parse.quote_plus(q)}&limit={posts_per_page}&sort=relevance&t={time_window}"
            if after:
                search_url += f"&after={after}"

            log(f" [RedditManager] Search URL: {search_url[:320]}")
            j = self._get_json(search_url)

            # debug: dump a small snippet of returned JSON for debugging
            if j is None:
                log(f" [RedditManager] No JSON returned for search URL.")
                break
            else:
                try:
                    snippet = json.dumps(j)[:1000]
                    log(f" [RedditManager] Search JSON snippet: {snippet}")
                except Exception:
                    log(" [RedditManager] Could not stringify search JSON snippet.")

            if not j or "data" not in j:
                log(" [RedditManager] Search returned no data or failed.")
                break

            children = j["data"].get("children", [])
            after = j["data"].get("after")
            if not children:
                log(" [RedditManager] Search returned zero children for this page.")
            for c in children:
                perm = c.get("data", {}).get("permalink")
                if not perm:
                    continue
                item = self._fetch_post_with_comments(perm, comments_limit)
                if item:
                    results["posts"].append(item)
                # polite pause between post fetches
                time.sleep(0.3)
            # polite pause between pages
            time.sleep(max(0.5, delay))
        return results


# ---- writer brief generator to match existing pipeline expectations ----
def generate_writer_brief(data: Dict[str, Any]) -> str:
    if not data or not data.get("posts"):
        return ""
    brief = f"--- REDDIT EVIDENCE FILE ---\nPrimary Topic: {data.get('query')}\n\n"
    for i, item in enumerate(data.get("posts", []), 1):
        p = item.get("post", {})
        brief += f"== THREAD #{i}: {p.get('title','N/A')} ==\n"
        brief += f"URL: {p.get('url','N/A')}\nUpvotes: {p.get('score',0)}\n"
        content = (p.get('text') or "").strip()
        if content:
            brief += f"Post Content: {content[:800]}{'...' if len(content) > 800 else ''}\n"
        # include top 3 comments in brief
        def fmt_comments(comments, level=0):
            nonlocal brief
            indent = "  " * level
            for c in (comments or [])[:3]:
                brief += f"{indent}- COMMENT by u/{c.get('author','N/A')} (Score: {c.get('score',0)}):\n"
                brief += f"{indent}  URL: {c.get('url','N/A')}\n"
                brief += f"{indent}  Text: {str(c.get('body',''))[:300].replace(chr(10),' ')}{'...' if len(c.get('body',''))>300 else ''}\n"
                if c.get('replies'):
                    fmt_comments(c.get('replies', []), level+1)
        if item.get("comments"):
            brief += "Community Discussion:\n"
            fmt_comments(item["comments"])
        brief += "\n"
    return brief


# ---- public adapter used by main.py pipeline ----
def get_community_intel(long_keyword: str):
    """
    Maintains same API used by main.py:
    Returns: (text_context: str, media_assets: List[dict])
    """
    log(f"🧠 [Reddit Manager] Initiating Graduated Search for: '{long_keyword}'")
    search_plan = []
    try:
        import ai_strategy
        search_plan = ai_strategy.generate_graduated_search_plan(long_keyword)
    except Exception as e:
        log(f" [RedditManager] ai_strategy import/generate failed: {e}. Falling back to raw keyword.")
        search_plan = [long_keyword]

    rm = RedditManager()
    final_data = None
    used_query = ""

    for idx, q in enumerate(search_plan):
        log(f" [Reddit Manager] Attempt {idx+1}/{len(search_plan)} -> '{q}'")
        raw = rm.search(q, pages=PAGES_TO_FETCH, posts_per_page=POSTS_PER_PAGE, comments_limit=COMMENTS_LIMIT, delay=REQUEST_DELAY)
        if raw and raw.get("posts"):
            final_data = raw
            used_query = q
            log(f" [Reddit Manager] Success: found {len(raw['posts'])} threads for '{q}'")
            break
        else:
            log(f" [Reddit Manager] No results for '{q}', continuing...")
    if not final_data:
        log(" [Reddit Manager] All search attempts failed. Returning empty result.")
        return "", []

    # generate text context and collect media assets
    text_context = generate_writer_brief(final_data)
    media_assets: List[Dict[str, Any]] = []

    def collect_media(comments, post_title):
        nonlocal media_assets
        for c in (comments or []):
            for m in c.get("media", []):
                media_assets.append({
                    "type": "image",
                    "url": m,
                    "description": f"Evidence from comment by u/{c.get('author','N/A')} on '{post_title}'",
                    "score": c.get("score", 0),
                    "source": "Reddit Comment"
                })
            if c.get("replies"):
                collect_media(c.get("replies", []), post_title)

    for item in final_data.get("posts", []):
        p = item.get("post", {})
        title_short = (p.get("title") or "")[:50]
        for m in p.get("media", []):
            media_assets.append({
                "type": "image",
                "url": m,
                "description": f"Community evidence for: {title_short}",
                "score": p.get("score", 0),
                "source": "Reddit Post"
            })
        if item.get("comments"):
            collect_media(item.get("comments", []), title_short)

    log(f" [Reddit Manager] Completed. Used query: '{used_query}'. Found {len(media_assets)} media assets.")
    return text_context, media_assets
