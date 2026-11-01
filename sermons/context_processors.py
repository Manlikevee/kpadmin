from datetime import timedelta

from django.utils import timezone

from church.models import Event
from .youtube import get_service


def live_stream(request):
    """Expose the live broadcast (if any) to every template for the navbar banner."""
    if request.path.startswith(("/portal", "/api", "/django-admin", "/static", "/media")):
        return {}
    poll_start = poll_end = ""
    now = timezone.now()
    try:
        candidates = []
        for event in Event.objects.filter(status=Event.Status.CONFIRMED).only("start_at", "end_at", "repeat"):
            occurrence = event.next_service_occurrence(after=now - timedelta(hours=6))
            if occurrence:
                end = (event.end_at if event.repeat == Event.Repeat.NONE and event.end_at else occurrence)
                if end >= now - timedelta(hours=6):
                    candidates.append((occurrence, end))
        if candidates:
            start, end = min(candidates, key=lambda pair: pair[0])
            poll_start = (start - timedelta(hours=6)).isoformat()
            poll_end = (end + timedelta(hours=6)).isoformat()
    except Exception:
        # A missing event schedule should not prevent the public page rendering.
        pass
    try:
        status = get_service().get_live_status()
    except Exception:  # the banner must never break a page
        return {}
    upcoming = status.get("upcoming")
    return {
        "live_stream": status.get("live"),
        "upcoming_stream": upcoming,
        "live_poll_start": poll_start,
        "live_poll_end": poll_end,
    }
