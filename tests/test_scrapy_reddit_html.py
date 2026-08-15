import unittest

from scrapy_reddit_html import parse_post_html, parse_search_html


SEARCH_HTML = """
<html><body>
<div class="thing link" data-permalink="/r/AI_Agents/comments/abc123/first_post/" data-subreddit="AI_Agents" data-author="alice" data-score="42">
  <a class="title" href="/r/AI_Agents/comments/abc123/first_post/">First useful post</a>
</div>
<div class="thing link" data-permalink="/r/automation/comments/def456/second_post/" data-subreddit="automation" data-author="bob" data-score="17">
  <a class="title" href="/r/automation/comments/def456/second_post/">Second useful post</a>
</div>
</body></html>
"""


POST_HTML = """
<html><body>
<div class="thing link" data-permalink="/r/AI_Agents/comments/abc123/first_post/" data-subreddit="AI_Agents" data-author="alice" data-score="42">
  <a class="title">First useful post</a>
  <div class="usertext-body"><div class="md"><p>This is the post body.</p><p>It contains an experiment.</p></div></div>
</div>
<div class="comment" data-fullname="t1_c1">
  <a class="author">reader_one</a><span class="score unvoted">12 points</span>
  <div class="md"><p>This is the first response.</p></div>
  <div class="child">
    <div class="comment" data-fullname="t1_c2">
      <a class="author">reader_two</a><span class="score unvoted">5 points</span>
      <div class="md"><p>This is a nested response.</p></div>
    </div>
  </div>
</div>
</body></html>
"""


CHALLENGE_HTML = "<html><body><h1>Prove your humanity</h1><p>Captcha required</p></body></html>"


class ScrapyRedditHtmlTests(unittest.TestCase):
    def test_search_extracts_multiple_posts(self):
        result = parse_search_html(SEARCH_HTML, "automation", posts_per_page=5)
        self.assertEqual(len(result["posts"]), 2)
        self.assertEqual(result["posts"][0]["title"], "First useful post")
        self.assertEqual(result["posts"][1]["subreddit"], "automation")
        self.assertEqual(result["parser"], "scrapy-selector")
        self.assertEqual(result["warnings"], [])

    def test_post_extracts_body_and_nested_comments(self):
        result = parse_post_html(POST_HTML, "/r/AI_Agents/comments/abc123/first_post/", comments_limit=10)
        self.assertEqual(result["post"]["title"], "First useful post")
        self.assertIn("post body", result["post"]["text"])
        self.assertEqual(result["comments_collected"], 2)
        self.assertEqual(result["comments"][0]["body"], "This is the first response.")
        self.assertEqual(result["comments"][0]["replies"][0]["body"], "This is a nested response.")

    def test_challenge_page_is_not_reported_as_content(self):
        result = parse_post_html(CHALLENGE_HTML, "/r/test/comments/abc/post/", comments_limit=10)
        self.assertEqual(result["comments_collected"], 0)
        self.assertTrue(any("content_unavailable" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
