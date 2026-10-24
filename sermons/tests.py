import io
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from sermons.youtube import YouTubeError, YouTubeService


def video(vid, live="none", thumbs=True):
    return {"id": vid, "snippet": {
        "title": f"Title {vid}", "description": "d", "publishedAt": "2026-10-11T09:00:00Z",
        "liveBroadcastContent": live,
        "thumbnails": {"high": {"url": f"https://img/{vid}.jpg"}} if thumbs else {}},
        "contentDetails": {"duration": "PT42M10S"}, "statistics": {"viewCount": "12"},
        "liveStreamingDetails": {}}


class FakeYouTube:
    def __init__(self, live_ids=(), missing=(), no_thumb=()):
        self.calls = []
        self.live_ids, self.missing, self.no_thumb = set(live_ids), set(missing), set(no_thumb)

    def __call__(self, svc, url):
        parsed = urlparse(url)
        endpoint = parsed.path.rsplit("/", 1)[-1]
        q = parse_qs(parsed.query)
        self.calls.append((endpoint, q))
        if endpoint == "channels":
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}]}
        if endpoint == "playlistItems":
            token = q.get("pageToken", [""])[0]
            ids = ["vid00003", "vid00004"] if token == "NEXT" else ["vid00001", "vid00002"]
            out = {"items": [{"contentDetails": {"videoId": i}} for i in ids]}
            if not token:
                out["nextPageToken"] = "NEXT"
            return out
        if endpoint == "videos":
            ids = q["id"][0].split(",")
            return {"items": [video(i, "live" if i in self.live_ids else "none", i not in self.no_thumb)
                              for i in ids if i not in self.missing]}
        raise AssertionError(endpoint)

    def count(self, endpoint):
        return sum(1 for e, _ in self.calls if e == endpoint)


@override_settings(YOUTUBE_API_KEY="test-key", YOUTUBE_CHANNEL_ID="UC_test")
class YouTubeServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def run_with(self, fake, fn):
        with mock.patch.object(YouTubeService, "_http_get", fake):
            return fn()

    def test_results_are_cached_across_calls(self):
        fake = FakeYouTube()
        svc = YouTubeService()
        first = self.run_with(fake, svc.get_sermons)
        second = self.run_with(fake, svc.get_sermons)
        self.assertEqual([v["video_id"] for v in first["items"]], ["vid00001", "vid00002"])
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(fake.count("playlistItems"), 1)
        self.assertEqual(fake.count("channels"), 1)

    def test_pagination_token_supports_archive_beyond_first_page(self):
        fake = FakeYouTube()
        svc = YouTubeService()
        page1 = self.run_with(fake, svc.get_sermons)
        page2 = self.run_with(fake, lambda: svc.get_sermons(page_token=page1["next_page_token"]))
        self.assertEqual([v["video_id"] for v in page2["items"]], ["vid00003", "vid00004"])

    def test_stale_cache_served_when_api_fails(self):
        fake = FakeYouTube()
        svc = YouTubeService()
        self.run_with(fake, svc.get_sermons)
        cache.delete(f"yt:page:UC_test:12:first")  # fresh copy expired, stale copy remains

        def boom(self_, url):
            raise urllib.error.URLError("down")

        page = self.run_with(boom, svc.get_sermons)
        self.assertTrue(page["stale"])
        self.assertEqual(len(page["items"]), 2)

    def test_quota_error_is_graceful_and_blocks_hammering(self):
        err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'))
        calls = []

        def quota(self_, url):
            calls.append(url)
            raise err

        svc = YouTubeService()
        page = self.run_with(quota, svc.get_sermons)
        self.assertEqual(page["items"], [])
        self.assertTrue(page["error"])
        n = len(calls)
        self.run_with(quota, svc.get_sermons)
        self.assertEqual(len(calls), n)  # blocked: no new HTTP calls during cool-down

    def test_missing_thumbnail_and_unavailable_video(self):
        fake = FakeYouTube(missing=["vid00002"], no_thumb=["vid00001"])
        page = self.run_with(fake, YouTubeService().get_sermons)
        self.assertEqual([v["video_id"] for v in page["items"]], ["vid00001"])
        self.assertEqual(page["items"][0]["thumbnail"], "")

    def test_no_api_key_does_not_raise(self):
        svc = YouTubeService(api_key="")
        self.assertEqual(svc.get_sermons()["items"], [])
        self.assertEqual(svc.get_live_status()["live"], None)

    def test_live_detected_then_disappears_when_broadcast_ends(self):
        svc = YouTubeService()
        live = FakeYouTube(live_ids=["vid00001"])
        self.assertEqual(self.run_with(live, svc.get_live_status)["live"]["video_id"], "vid00001")
        self.assertEqual(live.count("videos"), 1)
        self.run_with(live, svc.get_live_status)
        self.assertEqual(live.count("videos"), 1)  # cached for the live TTL
        cache.delete("yt:live:UC_test")  # TTL elapsed
        ended = FakeYouTube()
        self.assertIsNone(self.run_with(ended, svc.get_live_status)["live"])

    def test_stale_live_status_never_keeps_banner_up(self):
        svc = YouTubeService()
        self.run_with(FakeYouTube(live_ids=["vid00001"]), svc.get_live_status)
        cache.delete("yt:live:UC_test")

        def boom(self_, url):
            raise urllib.error.URLError("down")

        self.assertIsNone(self.run_with(boom, svc.get_live_status)["live"])


@override_settings(YOUTUBE_API_KEY="test-key", YOUTUBE_CHANNEL_ID="UC_test")
class SermonPagesTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_live_banner_on_public_pages_and_not_in_dashboard(self):
        fake = FakeYouTube(live_ids=["vid00001"])
        with mock.patch.object(YouTubeService, "_http_get", fake):
            html = self.client.get(reverse("core:home")).content.decode()
            self.assertIn("LIVE NOW", html)
            self.assertIn("https://www.youtube.com/watch?v=vid00001", html)
            self.assertEqual(self.client.get(reverse("sermons:live_status")).json()["live"]["video_id"], "vid00001")

    def test_sermon_pages_render_and_share_cache(self):
        fake = FakeYouTube()
        with mock.patch.object(YouTubeService, "_http_get", fake):
            self.assertContains(self.client.get(reverse("sermons:list")), "Title vid00001")
            self.assertContains(self.client.get(reverse("sermons:detail", args=["vid00001"])), "Title vid00001")
            self.assertContains(self.client.get(reverse("core:home")), "Title vid00001")
        self.assertEqual(fake.count("channels"), 1)

    def test_hidden_sermon_is_not_shown(self):
        from sermons.models import SermonNote
        SermonNote.objects.create(video_id="vid00001", is_hidden=True)
        with mock.patch.object(YouTubeService, "_http_get", FakeYouTube()):
            html = self.client.get(reverse("sermons:list")).content.decode()
        self.assertNotIn("Title vid00001", html)
        self.assertIn("Title vid00002", html)

    def test_invalid_video_id_404(self):
        with mock.patch.object(YouTubeService, "_http_get", FakeYouTube(missing=["bad_id_123"])):
            self.assertEqual(self.client.get(reverse("sermons:detail", args=["bad_id_123"])).status_code, 404)
