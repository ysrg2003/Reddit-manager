import unittest

from source_quality import assess_url, rank_urls


class SourceQualityTests(unittest.TestCase):
    def test_accepts_institutional_sources(self):
        result = assess_url("https://csrc.nist.gov/Projects/ssdf")
        self.assertTrue(result.eligible)
        self.assertEqual(result.tier, "A")
        self.assertGreaterEqual(result.score, 95)

    def test_rejects_unknown_domain(self):
        result = assess_url("https://example.com/article")
        self.assertFalse(result.eligible)
        self.assertEqual(result.tier, "reject")

    def test_rejects_non_https(self):
        result = assess_url("http://dora.dev/dora-report-2025")
        self.assertFalse(result.eligible)

    def test_rank_limits_batch_and_preserves_only_eligible_urls(self):
        urls = [
            "https://dora.dev/dora-report-2025",
            "https://example.com/weak-post",
            "https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent",
        ] * 5
        selected = rank_urls(urls, limit=10)
        self.assertLessEqual(len(selected), 10)
        self.assertTrue(all(item.eligible for item in selected))
        self.assertTrue(all("example.com" not in item.url for item in selected))


if __name__ == "__main__":
    unittest.main()
