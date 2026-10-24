"""Public sermon pages (uses the cached YouTube service)."""
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import SermonNote
from .youtube import get_service


def overlay_notes(videos):
    """Attach local metadata and drop videos hidden by an admin."""
    notes = {n.video_id: n for n in SermonNote.objects.filter(video_id__in=[v["video_id"] for v in videos])}
    out = []
    for v in videos:
        note = notes.get(v["video_id"])
        if note and note.is_hidden:
            continue
        v = dict(v, speaker=note.speaker if note else "", series=note.series if note else "",
                 featured=bool(note and note.is_featured))
        out.append(v)
    return out


def sermon_list(request):
    svc = get_service()
    page = svc.get_sermons(page_token=request.GET.get("page_token", ""), page_size=12)
    items = overlay_notes(page["items"])
    return render(request, "website/sermons.html", {
        "sermons": items, "page": page,
        "featured": items[0] if items and not request.GET.get("page_token") else None,
        "nav": "sermons",
    })


def sermon_detail(request, video_id):
    video = get_service().get_video(video_id)
    if not video:
        raise Http404("Sermon not found")
    video = overlay_notes([video])
    if not video:
        raise Http404("Sermon not found")
    related = overlay_notes(get_service().get_sermons(page_size=7)["items"])
    related = [v for v in related if v["video_id"] != video_id][:4]
    return render(request, "website/sermon.html", {"video": video[0], "related": related, "nav": "sermons"})


@require_GET
def live_status(request):
    """Polled by the navbar banner so it disappears when the broadcast ends."""
    status = get_service().get_live_status()
    live = status.get("live")
    upcoming = status.get("upcoming")
    return JsonResponse({
        "live": {"title": live["title"], "watch_url": live["watch_url"], "video_id": live["video_id"]} if live else None,
        "upcoming": {"title": upcoming["title"], "scheduled_start": upcoming["scheduled_start"]} if upcoming else None,
    })
