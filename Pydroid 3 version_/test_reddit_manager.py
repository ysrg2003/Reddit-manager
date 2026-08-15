# ==============================================================================
# Reddit Manager - Pydroid Optimized Edition (WWW.REDDIT Links, Configurable)
# ==============================================================================

import requests
import urllib.parse
import time
import re
from typing import List, Dict, Any, Optional
import urllib3

# -----------------------------
# CONFIGURABLE VARIABLES
# -----------------------------
SEARCH_QUERY = "python learning"   # موضوع البحث
PAGES_TO_FETCH = 2                 # عدد صفحات البحث
POSTS_PER_PAGE = 2                 # عدد المنشورات لكل صفحة
COMMENTS_LIMIT = 100               # عدد التعليقات لكل منشور
REQUEST_DELAY = 2                  # تأخير بين الطلبات بالثواني
# ==============================================================================

# Disable SSL warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class RedditManager:
    BASE_URL = "https://old.reddit.com"     # Fetch JSON from old.reddit
    OUTPUT_BASE = "https://www.reddit.com" # All links point to www.reddit.com

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Android 10; Mobile; rv:109.0) Gecko/109.0 Firefox/117.0",
            "Accept": "application/json"
        })

    # -----------------------------
    # Request with retry
    # -----------------------------
    def _get_json(self, url: str, retries: int = 3) -> Optional[Any]:
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=20, verify=False)
                if response.status_code == 429:
                    print("⚠ Rate limit hit. Sleeping 5 seconds...")
                    time.sleep(5)
                    continue
                response.raise_for_status()
                if "application/json" in response.headers.get("Content-Type", ""):
                    return response.json()
                return None
            except Exception as e:
                print(f"❌ Request error (attempt {attempt+1}):", e)
                time.sleep(2)
        return None

    # -----------------------------
    # Extract media URLs
    # -----------------------------
    def _extract_media(self, data: Dict[str, Any]) -> List[str]:
        media = []
        url = data.get("url", "")
        if any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", "v.redd.it", "imgur.com"]):
            media.append(url)
        text = data.get("selftext", "") or data.get("body", "")
        found = re.findall(r'(https?://[^\s)\]]+\.(?:jpg|jpeg|png|gif|mp4))', text, re.IGNORECASE)
        media.extend(found)
        return list(set(media))

    # -----------------------------
    # Recursive comment parser
    # -----------------------------
    def _parse_comments(self, children: List[Dict[str, Any]], post_permalink: str) -> List[Dict[str, Any]]:
        parsed = []
        for child in children:
            if child.get("kind") != "t1":
                continue
            data = child.get("data", {})
            body = data.get("body")
            if not body or body in ["[deleted]", "[removed]"]:
                continue

            comment_id = data.get("id")
            # Direct link to comment on www.reddit.com
            comment_link = f"{self.OUTPUT_BASE}{post_permalink}{comment_id}"

            replies = []
            if isinstance(data.get("replies"), dict):
                replies = self._parse_comments(
                    data["replies"]["data"]["children"],
                    post_permalink
                )

            parsed.append({
                "comment_id": comment_id,
                "author": data.get("author"),
                "body": body,
                "score": data.get("score", 0),
                "url": comment_link,
                "media": self._extract_media(data),
                "replies": replies
            })
        return parsed

    # -----------------------------
    # Fetch post + comments
    # -----------------------------
    def _fetch_post_with_comments(self, permalink: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_URL}{permalink}.json?limit={COMMENTS_LIMIT}"
        data = self._get_json(url)
        if not data or not isinstance(data, list) or len(data) < 2:
            return None
        try:
            post_data = data[0]["data"]["children"][0]["data"]
            comments_data = data[1]["data"]["children"]
            post_link = f"{self.OUTPUT_BASE}{permalink}"
            post = {
                "title": post_data.get("title"),
                "text": post_data.get("selftext"),
                "author": post_data.get("author"),
                "score": post_data.get("score", 0),
                "url": post_link,
                "media": self._extract_media(post_data)
            }
            comments = self._parse_comments(comments_data, permalink)
            return {"post": post, "comments": comments}
        except Exception as e:
            print("❌ Error parsing post:", e)
            return None

    # -----------------------------
    # Search with pagination
    # -----------------------------
    def search(self, query: str, pages: int = 1, posts_per_page: int = 3) -> Dict[str, Any]:
        results = {"query": query, "posts": []}
        after = None
        for page in range(pages):
            print(f"\n🔎 Fetching page {page+1}...\n")
            search_url = (
                f"{self.BASE_URL}/search.json?"
                f"q={urllib.parse.quote(query)}"
                f"&limit={posts_per_page}"
                f"&sort=relevance&t=month"
            )
            if after:
                search_url += f"&after={after}"
            search_data = self._get_json(search_url)
            if not search_data:
                break
            children = search_data["data"].get("children", [])
            after = search_data["data"].get("after")
            for child in children:
                permalink = child["data"].get("permalink")
                if not permalink:
                    continue
                post_data = self._fetch_post_with_comments(permalink)
                if post_data:
                    results["posts"].append(post_data)
            time.sleep(REQUEST_DELAY)
        return results


# ==============================================================================
# RUN SCRIPT
# ==============================================================================

manager = RedditManager()

data = manager.search(
    query=SEARCH_QUERY,
    pages=PAGES_TO_FETCH,
    posts_per_page=POSTS_PER_PAGE
)

print("\n==============================")
print("🔎 QUERY:", data["query"])
print("==============================\n")


def print_comments(comments_list, level=0):
    for c in comments_list:
        indent = "    " * level
        print(indent + "----------------------")
        print(indent + f"Author: {c['author']}")
        print(indent + f"Score: {c['score']}")
        print(indent + f"Link: {c['url']}")
        print(indent + f"Comment: {c['body'][:300]}")
        if c["media"]:
            print(indent + f"Media: {c['media']}")
        if c["replies"]:
            print_comments(c["replies"], level + 1)


for i, item in enumerate(data["posts"], 1):
    post = item["post"]
    comments = item["comments"]

    print("========================================")
    print(f"📌 POST #{i}")
    print("========================================")
    print("Title:", post["title"])
    print("Author:", post["author"])
    print("Score:", post["score"])
    print("Link:", post["url"])
    print("Text:\n", post["text"][:500] if post["text"] else "No text")
    if post["media"]:
        print("Media:", post["media"])

    print("\n💬 COMMENTS:\n")
    print_comments(comments)
    print("\n\n")

print("✅ Done")