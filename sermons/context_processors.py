from .youtube import get_service


def live_stream(request):
    """Expose the live broadcast (if any) to every template for the navbar banner."""
    if request.path.startswith(("/portal", "/api", "/django-admin", "/static", "/media")):
        return {}
    try:
        status = get_service().get_live_status()
    except Exception:  # the banner must never break a page
        return {}
    return {"live_stream": status.get("live"), "upcoming_stream": status.get("upcoming")}
