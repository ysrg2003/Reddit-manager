import json
import unittest
from unittest.mock import Mock

from reddit_manager import CollectorConfig, RedditFetchError, RedditManager, generate_writer_brief


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class TextResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class RedditManagerTests(unittest.TestCase):
    def make_manager(self, responses, **config_overrides):
        session = Mock()
        session.get.side_effect = responses
        defaults = {"direct_enabled": True}
        defaults.update(config_overrides)
        config = CollectorConfig(delay=0, retries=1, timeout=1, user_agent="test-agent", **defaults)
        return RedditManager(session=session, config=config), session

    def test_direct_transport_is_disabled_by_default(self):
        session = Mock()
        manager = RedditManager(session=session, config=CollectorConfig(delay=0))
        bundle = manager.search_with_fallback("test", provider="auto")
        self.assertEqual(bundle["transport"], "disabled")
        self.assertEqual(session.get.call_count, 0)
        self.assertTrue(any("No permitted fallback" in warning for warning in bundle["warnings"]))

    def test_search_normalizes_post_and_comments(self):
        search_payload = {
            "data": {
                "after": None,
                "children": [{"data": {"permalink": "/r/test/comments/abc/example/"}}],
            }
        }
        post_payload = [
            {"data": {"children": [{"data": {
                "id": "abc",
                "subreddit": "test",
                "title": "Example",
                "selftext": "A post",
                "author": "alice",
                "score": 42,
                "num_comments": 1,
                "permalink": "/r/test/comments/abc/example/",
            }}]}},
            {"data": {"children": [{"kind": "t1", "data": {
                "id": "c1",
                "author": "bob",
                "body": "A useful comment",
                "score": 9,
                "replies": "",
            }}]}},
        ]
        manager, session = self.make_manager([FakeResponse(search_payload), FakeResponse(post_payload)])
        bundle = manager.search("example", pages=1, posts_per_page=1, comments_limit=10)
        self.assertEqual(len(bundle["posts"]), 1)
        self.assertEqual(bundle["posts"][0]["title"], "Example")
        self.assertEqual(bundle["posts"][0]["comments"][0]["body"], "A useful comment")
        self.assertEqual(bundle["posts"][0]["evidence_type"], "community_signal")
        self.assertEqual(bundle["posts"][0]["comments"][0]["evidence_type"], "user_report")
        self.assertIn("unverified", bundle["evidence_policy"])
        self.assertEqual(session.get.call_count, 2)

    def test_writer_brief_preserves_urls_and_warning(self):
        bundle = {
            "query": "test",
            "retrieved_at": "2026-08-15T00:00:00+00:00",
            "posts": [{
                "title": "Example",
                "subreddit": "test",
                "url": "https://www.reddit.com/r/test/comments/abc/example/",
                "score": 4,
                "num_comments": 1,
                "evidence_type": "community_signal",
                "text": "Post body",
                "comments": [{
                    "author": "bob",
                    "score": 3,
                    "body": "Comment body",
                    "url": "https://www.reddit.com/r/test/comments/abc/example/c1/",
                    "replies": [],
                }],
            }],
            "warnings": ["one warning"],
        }
        brief = generate_writer_brief(bundle)
        self.assertIn("UNVERIFIED USER-GENERATED SIGNALS", brief)
        self.assertIn("https://www.reddit.com/r/test/comments/abc/example/c1/", brief)
        self.assertIn("one warning", brief)

    def test_retry_on_server_error(self):
        manager, session = self.make_manager([FakeResponse({}, 500), FakeResponse({"data": {"children": [], "after": None}})])
        bundle = manager.search("nothing", pages=1)
        self.assertEqual(bundle["posts"], [])
        self.assertEqual(session.get.call_count, 2)

    def test_scraper_key_failover_only_after_key_rejection(self):
        manager, session = self.make_manager(
            [FakeResponse({}, 403), TextResponse("")],
            direct_enabled=False,
            scraper_api_keys=[("scraper-1", "placeholder-1"), ("scraper-2", "placeholder-2")],
        )
        bundle = manager.search("fallback", pages=1)
        self.assertEqual(bundle["transport"], "scraperapi")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[0].args[0], "https://api.scraperapi.com")

    def test_scraperapi_html_listing_parses_posts(self):
        html = '''
        <shreddit-post post-id="abc" subreddit-prefixed-name="r/test"
          content-href="/r/test/comments/abc/example/" post-title="Example title" score="7" comment-count="2">
        </shreddit-post>
        '''
        manager, session = self.make_manager(
            [TextResponse(html)],
            direct_enabled=False,
            scraper_api_keys=[("scraper-1", "placeholder-1")],
        )
        bundle = manager.search_listing("example", posts_per_page=1)
        self.assertEqual(bundle["transport"], "scraperapi")
        self.assertEqual(len(bundle["posts"]), 1)
        self.assertEqual(bundle["posts"][0]["title"], "Example title")
        self.assertEqual(bundle["posts"][0]["url"], "https://old.reddit.com/r/test/comments/abc/example/")
        self.assertEqual(session.get.call_args.args[0], "https://api.scraperapi.com")
        self.assertEqual(session.get.call_args.kwargs["params"]["url"].split("?")[0], "https://old.reddit.com/search.json")

    def test_scraperapi_scrapy_fetches_post_html_and_comments(self):
        search_html = '''
        <div class="thing link" data-permalink="/r/test/comments/abc/example/" data-subreddit="test">
          <a class="title" href="/r/test/comments/abc/example/">Example title</a>
        </div>
        '''
        post_html = '''
        <div class="thing link" data-permalink="/r/test/comments/abc/example/" data-subreddit="test">
          <a class="title">Example title</a>
          <div class="usertext-body"><div class="md"><p>Post body from HTML.</p></div></div>
        </div>
        <div class="comment" data-fullname="t1_c1"><a class="author">reader</a><div class="md"><p>Comment from HTML.</p></div></div>
        '''
        manager, session = self.make_manager(
            [TextResponse(search_html), TextResponse(post_html)],
            direct_enabled=False,
            scraper_api_keys=[("scraper-1", "placeholder-1")],
        )
        bundle = manager.search("example", pages=1, posts_per_page=1, comments_limit=10)
        self.assertEqual(len(bundle["posts"]), 1)
        self.assertEqual(bundle["posts"][0]["content_status"], "post_html_parsed")
        self.assertEqual(bundle["posts"][0]["text"], "Post body from HTML.")
        self.assertEqual(bundle["posts"][0]["comments"][0]["body"], "Comment from HTML.")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[0].kwargs["params"]["url"].split("?")[0], "https://old.reddit.com/search.json")
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["url"], "https://old.reddit.com/r/test/comments/abc/example/")

    def test_scraper_quota_does_not_rotate_keys(self):
        manager, session = self.make_manager(
            [FakeResponse({}, 429), FakeResponse({"data": {"children": [], "after": None}})],
            direct_enabled=False,
            scraper_api_keys=[("scraper-1", "placeholder-1"), ("scraper-2", "placeholder-2")],
        )
        bundle = manager.search("quota", pages=1)
        self.assertEqual(session.get.call_count, 1)
        self.assertTrue(any("quota/rate limit" in warning for warning in bundle["warnings"]))

    def test_oauth_is_not_sent_to_proxy(self):
        manager, session = self.make_manager(
            [FakeResponse({"data": {"children": [], "after": None}})],
            access_token="secret-token",
            scraper_api_keys=[("scraper-1", "placeholder")],
        )
        bundle = manager.search("oauth", pages=1)
        self.assertEqual(bundle["transport"], "direct")
        self.assertEqual(session.get.call_args_list[0].args[0], "https://oauth.reddit.com/search.json")
        self.assertNotIn("secret-token", str(session.get.call_args_list[0].kwargs))

    def test_brave_search_parses_only_reddit_urls(self):
        payload = {"web": {"results": [
            {"title": "Reddit thread", "url": "https://www.reddit.com/r/test/comments/abc/example/", "description": "A snippet"},
            {"title": "Other site", "url": "https://example.com/page", "description": "Ignore me"},
        ]}}
        manager, session = self.make_manager([FakeResponse(payload)], brave_api_key="brave-placeholder")
        bundle = manager.search_with_fallback("test", provider="brave", posts_per_page=5)
        self.assertEqual(bundle["transport"], "brave_search_api")
        self.assertEqual(len(bundle["posts"]), 1)
        self.assertEqual(bundle["posts"][0]["evidence_type"], "community_search_snippet")
        self.assertIn("X-Subscription-Token", session.get.call_args.kwargs["headers"])

    def test_empty_query_is_rejected(self):
        manager, _ = self.make_manager([])
        with self.assertRaises(ValueError):
            manager.search(" ")

    def test_bad_json_raises_after_retries(self):
        manager, _ = self.make_manager([FakeResponse(json.JSONDecodeError("bad", "", 0)), FakeResponse(json.JSONDecodeError("bad", "", 0))])
        with self.assertRaises(RedditFetchError):
            manager._request_json("/search.json")


if __name__ == "__main__":
    unittest.main()
