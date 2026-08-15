"""Scrapy-based parser for Reddit HTML returned by ScraperAPI.

This module parses only content present in the received HTML. It does not
pretend that a challenge page contains a post or comments.
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable
from urllib.parse import urljoin

from scrapy import Selector


REDDIT_BASE = "https://old.reddit.com"
POST_HREF_RE = re.compile(r"^/r/[^/]+/comments/[^/]+(?:/|$)")
CHALLENGE_MARKERS = (
    "prove your humanity",
    "captcha",
    "you've been blocked",
    "you have been blocked",
    "robot check",
)


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(value).split()).strip()


def _safe_permalink(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.split("?", 1)[0].strip()
    if not value.startswith("/") or ".." in value:
        return ""
    return value


def _int_or_none(value: Any) -> int | None:
    text = _clean(value).replace(",", "")
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _absolute(permalink: str) -> str:
    return urljoin(REDDIT_BASE, permalink)


def _post_from_old_thing(node: Selector) -> dict[str, Any]:
    permalink = _safe_permalink(node.attrib.get("data-permalink"))
    if not permalink:
        href = node.css("a.title::attr(href)").get(default="")
        permalink = _safe_permalink(href)
    title = _clean(node.css("a.title::text").get(default=""))
    if not title:
        title = _clean(node.css("[data-testid='post-title'] ::text").get(default=""))
    subreddit = _clean(node.attrib.get("data-subreddit"))
    author = _clean(node.attrib.get("data-author"))
    score = _int_or_none(node.attrib.get("data-score"))
    if score is None:
        score = _int_or_none(node.css("div.score.unvoted::text").get(default=""))
    num_comments = _int_or_none(node.attrib.get("data-comments-count"))
    if num_comments is None:
        comments_label = node.css("a.comments::text").get(default="")
        num_comments = _int_or_none(comments_label)
    post_id = _clean(node.attrib.get("data-fullname"))
    if post_id.startswith("t3_"):
        post_id = post_id[3:]
    if not post_id:
        post_id = _clean(node.attrib.get("id")).removeprefix("thing_")
    return {
        "post_id": post_id,
        "subreddit": subreddit,
        "title": title,
        "text": "",
        "author": author,
        "score": score,
        "num_comments": num_comments,
        "url": _absolute(permalink) if permalink else "",
        "permalink": permalink,
    }


def _post_from_shreddit(node: Selector) -> dict[str, Any]:
    attrs = node.attrib
    permalink = _safe_permalink(attrs.get("content-href") or attrs.get("permalink") or attrs.get("href"))
    title = _clean(attrs.get("post-title") or attrs.get("title"))
    if not title:
        title = _clean(node.css("[slot='title'] ::text").get(default=""))
    subreddit = _clean(attrs.get("subreddit-prefixed-name") or attrs.get("subreddit-name") or attrs.get("subreddit"))
    subreddit = subreddit.removeprefix("r/")
    return {
        "post_id": _clean(attrs.get("post-id") or attrs.get("id")),
        "subreddit": subreddit,
        "title": title,
        "text": "",
        "author": _clean(attrs.get("author")),
        "score": _int_or_none(attrs.get("score") or attrs.get("score-value")),
        "num_comments": _int_or_none(attrs.get("comment-count") or attrs.get("num-comments")),
        "url": _absolute(permalink) if permalink else "",
        "permalink": permalink,
    }


def _anchor_search_posts(selector: Selector) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    for anchor in selector.css("a[href]"):
        href = _safe_permalink(anchor.attrib.get("href"))
        if not POST_HREF_RE.match(href):
            continue
        title = _clean(" ".join(anchor.css("::text").getall()))
        if not title:
            continue
        match = re.match(r"^/r/([^/]+)/comments/([^/]+)/", href)
        if not match:
            continue
        posts.append({
            "post_id": match.group(2),
            "subreddit": match.group(1),
            "title": title,
            "text": "",
            "author": "",
            "score": None,
            "num_comments": None,
            "url": _absolute(href),
            "permalink": href,
        })
    return posts


def _dedupe_posts(posts: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for post in posts:
        key = post.get("permalink") or post.get("post_id") or post.get("url")
        if not key or key in seen or not post.get("title"):
            continue
        seen.add(key)
        result.append(post)
        if len(result) >= max(1, min(int(limit), 100)):
            break
    return result


def parse_search_html(content: str, query: str, posts_per_page: int = 10) -> dict[str, Any]:
    selector = Selector(text=content or "")
    posts: list[dict[str, Any]] = []
    posts.extend(_post_from_old_thing(node) for node in selector.css("div.thing[data-permalink]"))
    posts.extend(_post_from_shreddit(node) for node in selector.css("shreddit-post"))
    posts.extend(_anchor_search_posts(selector))
    unique = _dedupe_posts(posts, posts_per_page)
    body_text = _clean(" ".join(selector.css("body ::text").getall())).lower()
    warnings: list[str] = []
    if not unique:
        if any(marker in body_text for marker in CHALLENGE_MARKERS):
            warnings.append("content_unavailable: Reddit returned a challenge page; no post listing was present.")
        else:
            warnings.append("no_match: HTML was received but no Reddit post cards were recognized.")
    return {
        "posts": unique,
        "warnings": warnings,
        "parser": "scrapy-selector",
        "source_format": "html",
    }


def _comment_from_node(node: Selector, permalink: str, depth: int) -> dict[str, Any] | None:
    markdown_nodes = node.css("div.md")
    body = _clean(" ".join(markdown_nodes[0].xpath(".//text()").getall())) if markdown_nodes else ""
    if not body:
        return None
    author = _clean(node.css("a.author::text").get(default=""))
    score = _int_or_none(node.css("span.score.unvoted::text").get(default=""))
    comment_id = _clean(node.attrib.get("data-fullname") or node.attrib.get("id"))
    comment_id = comment_id.removeprefix("t1_").removeprefix("thing_")
    comment_url = f"{_absolute(permalink)}{comment_id}" if comment_id else _absolute(permalink)
    return {
        "evidence_type": "user_report",
        "comment_id": comment_id,
        "author": author,
        "body": body,
        "score": score or 0,
        "depth": depth,
        "url": comment_url,
        "media": [],
        "replies": [],
    }


def _parse_nested_comments(node: Selector, permalink: str, depth: int, limit: int, state: dict[str, int]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    if state["count"] >= limit:
        return comments
    for child in node.xpath("./div[contains(concat(' ', normalize-space(@class), ' '), ' comment ')]"):
        if state["count"] >= limit:
            break
        item = _comment_from_node(child, permalink, depth)
        if item is None:
            continue
        state["count"] += 1
        child_container = child.xpath("./div[contains(concat(' ', normalize-space(@class), ' '), ' child ')]")
        item["replies"] = _parse_nested_comments(child_container, permalink, depth + 1, limit, state)
        comments.append(item)
    return comments


def parse_post_html(content: str, permalink: str, comments_limit: int = 100) -> dict[str, Any]:
    selector = Selector(text=content or "")
    post_nodes = selector.css("div.thing.link[data-permalink]")
    if post_nodes:
        post = _post_from_old_thing(post_nodes[0])
        title = _clean(post_nodes[0].css("a.title::text").get(default=""))
        post["title"] = title or post["title"]
        post["text"] = _clean(" ".join(post_nodes[0].css("div.usertext-body div.md ::text").getall()))
    else:
        shreddit_nodes = selector.css("shreddit-post")
        post = _post_from_shreddit(shreddit_nodes[0]) if shreddit_nodes else {
            "post_id": "", "subreddit": "", "title": "", "text": "", "author": "",
            "score": None, "num_comments": None, "url": _absolute(permalink), "permalink": permalink,
        }
        if shreddit_nodes:
            post["text"] = _clean(" ".join(shreddit_nodes[0].css("[slot='text'] ::text, .md ::text").getall()))
    post["permalink"] = post.get("permalink") or permalink
    post["url"] = _absolute(post["permalink"])
    state = {"count": 0}
    limit = max(0, min(int(comments_limit), 500))
    comments: list[dict[str, Any]] = []
    roots = selector.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' comment ') "
        "and not(ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' comment ')])]"
    )
    for root in roots:
        if state["count"] >= limit:
            break
        item = _comment_from_node(root, post["permalink"], 0)
        if item is None:
            continue
        state["count"] += 1
        child_container = root.xpath("./div[contains(concat(' ', normalize-space(@class), ' '), ' child ')]")
        item["replies"] = _parse_nested_comments(child_container, post["permalink"], 1, limit, state)
        comments.append(item)
    body_text = _clean(" ".join(selector.css("body ::text").getall())).lower()
    warnings: list[str] = []
    if not post.get("title") and any(marker in body_text for marker in CHALLENGE_MARKERS):
        warnings.append("content_unavailable: Reddit returned a challenge page; post text and comments are unavailable.")
    elif not post.get("title"):
        warnings.append("content_unavailable: no post body was recognized in the returned HTML.")
    return {
        "post": post,
        "comments": comments,
        "comments_collected": state["count"],
        "warnings": warnings,
        "parser": "scrapy-selector",
        "source_format": "html",
    }
