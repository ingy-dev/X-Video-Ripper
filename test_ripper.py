import unittest

from ripper import RipError, parse_post_url, prepare_variants, safe_filename, syndication_token, validate_media_url


class RipperTests(unittest.TestCase):
    def test_syndication_token_matches_embed_widget(self):
        cases = {
            "1874097816571961839": "4jjngwkifa",
            "1674700676612386816": "42586mwa3uv",
            "1877747914073620506": "4jv4aahw36n",
            "1876710769913450647": "4jruzjz5lux",
            "1346554693649113090": "39ibqxei7mo",
        }
        for tweet_id, token in cases.items():
            self.assertEqual(syndication_token(tweet_id), token)

    def test_parse_post_links(self):
        samples = [
            "https://x.com/NASA/status/2102748685792596449",
            "https://twitter.com/NASA/status/2102748685792596449?s=20",
            "https://x.com/NASA/status/2102748685792596449/video/1",
            "https://mobile.twitter.com/NASA/status/2102748685792596449",
            "https://fxtwitter.com/NASA/status/2102748685792596449",
            "x.com/NASA/status/2102748685792596449",
        ]
        for sample in samples:
            parsed = parse_post_url(sample)
            self.assertEqual(parsed["id"], "2102748685792596449")
            self.assertEqual(parsed["handle"], "NASA")

        self.assertEqual(parse_post_url("https://x.com/i/status/2102748685792596449")["handle"], None)
        web = parse_post_url("https://x.com/i/web/status/2102748685792596449")
        self.assertEqual(web["id"], "2102748685792596449")
        self.assertIsNone(web["handle"])
        self.assertEqual(parse_post_url("2102748685792596449")["id"], "2102748685792596449")

    def test_reject_unrelated_links(self):
        for sample in ("https://example.com/watch?v=1", "hello", "https://x.com/NASA"):
            with self.assertRaises(RipError):
                parse_post_url(sample)

    def test_variants_prefer_highest_quality_mp4(self):
        variants = prepare_variants(
            [
                {
                    "content_type": "application/x-mpegURL",
                    "url": "https://video.twimg.com/amplify_video/1/pl/stream.m3u8",
                },
                {
                    "bitrate": 832000,
                    "content_type": "video/mp4",
                    "url": "https://video.twimg.com/ext_tw_video/1/vid/avc1/640x360/a.mp4",
                },
                {
                    "bitrate": 2176000,
                    "content_type": "video/mp4",
                    "url": "https://video.twimg.com/ext_tw_video/1/vid/avc1/1280x720/b.mp4",
                },
            ]
        )
        self.assertEqual([item["label"] for item in variants], ["720p", "360p"])
        self.assertTrue(variants[0]["url"].endswith("/b.mp4"))

    def test_media_url_must_be_the_video_cdn(self):
        validate_media_url("https://video.twimg.com/ext_tw_video/1/vid/avc1/1280x720/b.mp4")
        for sample in (
            "http://video.twimg.com/a.mp4",
            "https://evil.example/a.mp4",
            "https://user:pass@video.twimg.com/a.mp4",
            "https://video.twimg.com:8080/a.mp4",
        ):
            with self.assertRaises(RipError):
                validate_media_url(sample)

    def test_filename_is_a_safe_mp4(self):
        self.assertEqual(safe_filename("NASA 1080p!.mp4"), "NASA-1080p.mp4")
        self.assertEqual(safe_filename("../etc/passwd"), "etc-passwd.mp4")


if __name__ == "__main__":
    unittest.main()
