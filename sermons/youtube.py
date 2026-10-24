"""YouTube Data API integration with caching.

* One service is used by the website, dashboards and the mobile API.
* The API key is read from settings (``YOUTUBE_API_KEY`` env var) and never
  reaches the browser.
* Normal sermon data is cached for ``YOUTUBE_CACHE_SECONDS`` (default 15 min),
  live status for ``YOUTUBE_LIVE_CACHE_SECONDS`` (default 2 min).
* Every fresh result is also stored in a long-lived "stale" key so pages keep
  working when YouTube is unreachable or the quota is exhausted.
"""
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/youtube/v3"
PLACEHOLDER_THUMB = "site/logo.png"  # static path used when a video has no thumbnail
QUOTA_BLOCK_SECONDS = 60 * 60
FAIL_BACKOFF_SECONDS = 30
MAX_PAGE_SIZE = 50


class YouTubeError(Exception):
    pass


class YouTubeNotConfigured(YouTubeError):
    pass


class YouTubeQuotaExceeded(YouTubeError):
    pass


def _fmt_duration(iso):
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return ""
    h, mi, s = (int(x or 0) for x in m.groups())
    return f"{h}:{mi:02d}:{s:02d}" if h else f"{mi}:{s:02d}"


def _best_thumbnail(thumbs):
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = (thumbs or {}).get(key, {}).get("url")
        if url:
            return url
    return ""


def normalise_video(item):
    """Convert a ``videos.list`` item to the plain dict used everywhere else."""
    snippet = item.get("snippet", {})
    live = item.get("liveStreamingDetails", {})
    status = snippet.get("liveBroadcastContent", "none")  # live | upcoming | none
    vid = item["id"]
    return {
        "video_id": vid,
        "title": snippet.get("title", "Untitled"),
        "description": snippet.get("description", ""),
        "thumbnail": _best_thumbnail(snippet.get("thumbnails")),
        "published_at": snippet.get("publishedAt", ""),
        "watch_url": f"https://www.youtube.com/watch?v={vid}",
        "embed_url": f"https://www.youtube.com/embed/{vid}",
        "duration": _fmt_duration(item.get("contentDetails", {}).get("duration")),
        "view_count": int(item.get("statistics", {}).get("viewCount", 0) or 0),
        "live_status": status if status in ("live", "upcoming") else "none",
        "is_live": status == "live",
        "scheduled_start": live.get("scheduledStartTime", ""),
        "actual_start": live.get("actualStartTime", ""),
        "actual_end": live.get("actualEndTime", ""),
    }


class YouTubeService:
    def __init__(self, api_key=None, channel_id=None):
        self.api_key = api_key if api_key is not None else settings.YOUTUBE_API_KEY
        self.channel_id = channel_id or settings.YOUTUBE_CHANNEL_ID
        self.ttl = settings.YOUTUBE_CACHE_SECONDS
        self.live_ttl = settings.YOUTUBE_LIVE_CACHE_SECONDS
        self.stale_ttl = settings.YOUTUBE_STALE_SECONDS

    # ------------------------------------------------------------------ HTTP
    def _http_get(self, url):  # isolated so tests can patch it
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _call(self, resource, **params):
        if not self.api_key:
            raise YouTubeNotConfigured("YOUTUBE_API_KEY is not set.")
        if cache.get("yt:quota_blocked"):
            raise YouTubeQuotaExceeded("YouTube quota recently exhausted; using cached data.")
        params["key"] = self.api_key
        url = f"{API_ROOT}/{resource}?{urllib.parse.urlencode(params)}"
        try:
            return self._http_get(url)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "ignore")
            except Exception:  # pragma: no cover
                pass
            if exc.code in (403, 429) and ("quota" in body.lower() or "rateLimit" in body):
                cache.set("yt:quota_blocked", True, QUOTA_BLOCK_SECONDS)
                raise YouTubeQuotaExceeded("YouTube API quota exceeded.") from exc
            raise YouTubeError(f"YouTube API error {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise YouTubeError(f"YouTube request failed: {exc}") from exc

    # ------------------------------------------------------------ cache helper
    def _cached(self, key, ttl, loader):
        """Fresh cache -> loader -> stale copy. Returns (value, is_stale) or raises."""
        value = cache.get(key)
        if value is not None:
            return value, False
        stale = cache.get(f"{key}:stale")
        if cache.get(f"{key}:fail"):
            # YouTube failed moments ago: don't make every request wait on a timeout
            if stale is not None:
                return stale, True
            raise YouTubeError("YouTube temporarily unavailable.")
        try:
            value = loader()
        except YouTubeNotConfigured:
            raise
        except YouTubeError as exc:
            cache.set(f"{key}:fail", True, FAIL_BACKOFF_SECONDS)
            if stale is not None:
                logger.warning("YouTube unavailable (%s); serving stale cache for %s", exc, key)
                return stale, True
            raise
        cache.set(key, value, ttl)
        cache.set(f"{key}:stale", value, self.stale_ttl)
        return value, False

    # --------------------------------------------------------------- lookups
    def uploads_playlist_id(self):
        def load():
            data = self._call("channels", part="contentDetails", id=self.channel_id)
            items = data.get("items") or []
            if not items:
                raise YouTubeError("Channel not found.")
            return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        try:
            value, _ = self._cached("yt:uploads_playlist", 60 * 60 * 24, load)
            return value
        except YouTubeNotConfigured:
            raise
        except YouTubeError:
            # The uploads playlist id is deterministic: UC... -> UU...
            if self.channel_id.startswith("UC"):
                return "UU" + self.channel_id[2:]
            raise

    def _videos_by_ids(self, ids):
        if not ids:
            return []
        data = self._call(
            "videos", part="snippet,contentDetails,liveStreamingDetails,statistics",
            id=",".join(ids), maxResults=MAX_PAGE_SIZE,
        )
        by_id = {it["id"]: normalise_video(it) for it in data.get("items", [])}
        # keep playlist order; unavailable/private videos are simply absent
        return [by_id[i] for i in ids if i in by_id]

    def get_sermons(self, page_token="", page_size=12):
        """One page of the uploads archive. Page tokens let the archive grow past 50 videos.

        Returns ``{"items", "next_page_token", "prev_page_token", "stale", "error"}``;
        never raises — on failure with nothing cached, ``items`` is empty and ``error`` is set.
        """
        page_size = max(1, min(int(page_size or 12), MAX_PAGE_SIZE))
        page_token = page_token or ""

        def load():
            params = dict(part="contentDetails", playlistId=self.uploads_playlist_id(), maxResults=page_size)
            if page_token:
                params["pageToken"] = page_token
            data = self._call("playlistItems", **params)
            ids = [i["contentDetails"]["videoId"] for i in data.get("items", [])
                   if i.get("contentDetails", {}).get("videoId")]
            return {
                "items": self._videos_by_ids(ids),
                "next_page_token": data.get("nextPageToken", ""),
                "prev_page_token": data.get("prevPageToken", ""),
            }

        key = f"yt:page:{self.channel_id}:{page_size}:{page_token or 'first'}"
        try:
            page, stale = self._cached(key, self.ttl, load)
            return {**page, "stale": stale, "error": ""}
        except YouTubeError as exc:
            return {"items": [], "next_page_token": "", "prev_page_token": "", "stale": False, "error": str(exc)}

    def get_video(self, video_id):
        """Single video, using any cached page first to avoid an extra API call."""
        if not re.fullmatch(r"[\w-]{6,20}", video_id or ""):
            return None
        key = f"yt:video:{video_id}"
        try:
            value, _ = self._cached(key, self.ttl, lambda: (self._videos_by_ids([video_id]) or [None])[0])
            return value
        except YouTubeError:
            return None

    # ----------------------------------------------------------------- live
    def get_live_status(self):
        """Current broadcast and the next scheduled one.

        ``{"live": video|None, "upcoming": video|None, "stale": bool}``. Never raises.
        Uses the cheap path: recent uploads (live/scheduled streams appear in the
        uploads playlist) checked with ``videos.list`` — 2 quota units, not the
        100-unit ``search.list``.
        """
        def load():
            data = self._call("playlistItems", part="contentDetails",
                              playlistId=self.uploads_playlist_id(), maxResults=10)
            ids = [i["contentDetails"]["videoId"] for i in data.get("items", [])
                   if i.get("contentDetails", {}).get("videoId")]
            videos = self._videos_by_ids(ids)
            live = next((v for v in videos if v["live_status"] == "live"), None)
            upcoming = sorted((v for v in videos if v["live_status"] == "upcoming"),
                              key=lambda v: v["scheduled_start"] or "9999")
            return {"live": live, "upcoming": upcoming[0] if upcoming else None}

        try:
            value, stale = self._cached(f"yt:live:{self.channel_id}", self.live_ttl, load)
        except YouTubeError:
            return {"live": None, "upcoming": None, "stale": False}
        # A stale "live" result must not keep the banner up forever after an outage.
        if stale:
            value = {"live": None, "upcoming": value.get("upcoming")}
        return {**value, "stale": stale}

    def clear_cache(self):
        """Used by the dashboard "Refresh from YouTube" button (stale copies are kept)."""
        for key in ("yt:uploads_playlist",):
            cache.delete(key)
        cache.delete(f"yt:live:{self.channel_id}")
        cache.delete("yt:quota_blocked")
        for size in (6, 12, 20, 24, 50):
            cache.delete(f"yt:page:{self.channel_id}:{size}:first")


def parse_iso(value):
    return parse_datetime(value) if value else None


def get_service():
    return YouTubeService()
