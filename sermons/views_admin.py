"""Dashboard views for sermons (staff only; metadata overlay on YouTube data)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.decorators.http import require_POST

from accounts.mixins import StaffRequiredMixin

from .forms import SermonNoteForm
from .models import SermonNote
from .youtube import get_service


class SermonAdminList(StaffRequiredMixin, View):
    def get(self, request):
        page = get_service().get_sermons(page_token=request.GET.get("page_token", ""), page_size=12)
        notes = {n.video_id: n for n in SermonNote.objects.filter(
            video_id__in=[v["video_id"] for v in page["items"]])}
        items = [dict(v, note=notes.get(v["video_id"])) for v in page["items"]]
        return render(request, "dashboard/sermons-media.html", {"sermons": items, "page": page, "page_id": "sermons-media"})


def _staff_only(user):
    if not (user.is_authenticated and user.is_staff_role):
        raise PermissionDenied


@login_required
def sermon_admin_detail(request, video_id):
    _staff_only(request.user)
    video = get_service().get_video(video_id)
    if not video:
        raise Http404
    note = SermonNote.objects.filter(video_id=video_id).first()
    return render(request, "dashboard/sermon-detail.html", {"video": video, "note": note, "page_id": "sermons-media"})


@login_required
def sermon_admin_edit(request, video_id):
    _staff_only(request.user)
    video = get_service().get_video(video_id)
    if not video:
        raise Http404
    note, _ = SermonNote.objects.get_or_create(video_id=video_id)
    form = SermonNoteForm(request.POST or None, instance=note)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sermon details saved.")
        return redirect("sermons_admin:detail", video_id=video_id)
    return render(request, "dashboard/sermon-form.html",
                  {"form": form, "video": video, "page_id": "sermons-media",
                   "list_url": "sermons_admin:list", "delete_url": ""})


@login_required
@require_POST
def refresh_cache(request):
    _staff_only(request.user)
    get_service().clear_cache()
    messages.success(request, "Refreshed from YouTube.")
    return redirect("sermons_admin:list")
