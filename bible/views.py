
import logging

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from accounts.mixins import SuperAdminRequiredMixin

from .forms import BibleUploadForm
from .models import BibleTranslation, human_size
logger = logging.getLogger(__name__)

class BibleListView(SuperAdminRequiredMixin, View):
    def get(self, request):
        items = BibleTranslation.objects.all()

        total = sum(item.size_in_bytes for item in items)
        biggest = max(
            items,
            key=lambda item: item.size_in_bytes,
            default=None,
        )

        return render(
            request,
            "dashboard/bible-management.html",
            {
                "translations": items,
                "total_size": human_size(total),
                "largest": biggest,
                "page_id": "bible-management",
            },
        )


class BibleUploadView(SuperAdminRequiredMixin, View):
    def post(self, request):
        form = BibleUploadForm(request.POST, request.FILES)

        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)

            return redirect("bible:list")

        try:
            uploaded_file = form.cleaned_data["file"]

            translation = BibleTranslation(
                name=form.cleaned_data["name"],
                file=uploaded_file,
                uploaded_by=request.user,
                size_in_bytes=uploaded_file.size,
            )

            translation.save()

            messages.success(
                request,
                f"{translation.name} uploaded successfully.",
            )

        except Exception as exc:
            logger.exception("Bible translation upload failed")

            if settings.DEBUG:
                messages.error(
                    request,
                    f"Upload failed: {type(exc).__name__}: {exc}",
                )
            else:
                messages.error(
                    request,
                    "Upload failed. Please check the server logs.",
                )

        return redirect("bible:list")
class BibleReplaceView(SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        old_file = obj.file.name if obj.file else None

        form = BibleUploadForm(
            request.POST,
            request.FILES,
            instance=obj,
        )

        if form.is_valid():
            try:
                translation = form.save(commit=False)
                translation.name = form.cleaned_data["name"].strip().upper()
                translation.uploaded_by = request.user
                translation.save()

                # Delete the old Cloudinary asset only after the new
                # file has been saved successfully.
                if (
                    old_file
                    and old_file != translation.file.name
                ):
                    from cloudinary import uploader

                    uploader.destroy(
                        old_file,
                        resource_type="raw",
                        invalidate=True,
                    )

                messages.success(
                    request,
                    f"{translation.name} replaced successfully.",
                )
            except Exception:
                messages.error(
                    request,
                    "Replacement failed. Check Cloudinary and try again.",
                )
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)

        return redirect("bible:list")


class BibleDeleteView(SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        name = obj.name

        try:
            if obj.file:
                from cloudinary import uploader

                # Use the stored Cloudinary public ID, not file.path.
                uploader.destroy(
                    obj.file.name,
                    resource_type="raw",
                    invalidate=True,
                )

            obj.delete()

            messages.success(
                request,
                f"{name} deleted successfully.",
            )
        except Exception:
            messages.error(
                request,
                "Deletion failed. Check Cloudinary and try again.",
            )

        return redirect("bible:list")
