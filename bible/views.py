from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from accounts.mixins import SuperAdminRequiredMixin

from .forms import BibleUploadForm
from .models import BibleTranslation, assert_in_bible_dir, human_size


class BibleListView(SuperAdminRequiredMixin, View):
    def get(self, request):
        items = BibleTranslation.objects.all()
        total = sum(i.size_in_bytes for i in items)
        biggest = max(items, key=lambda i: i.size_in_bytes, default=None)
        return render(request, "dashboard/bible-management.html", {
            "translations": items, "total_size": human_size(total), "largest": biggest,
            "page_id": "bible-management",
        })


class BibleUploadView(SuperAdminRequiredMixin, View):
    def post(self, request):
        form = BibleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            BibleTranslation.objects.create(
                name=form.cleaned_data["name"], file=form.cleaned_data["file"], uploaded_by=request.user)
            messages.success(request, f"{form.cleaned_data['name']} uploaded.")
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
        return redirect("bible:list")


class BibleReplaceView(SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        form = BibleUploadForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            obj.name = form.cleaned_data["name"]
            obj.file = form.cleaned_data["file"]  # django-cleanup removes the old file
            obj.uploaded_by = request.user
            obj.save()
            messages.success(request, f"{obj.name} replaced.")
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
        return redirect("bible:list")


class BibleDeleteView(SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        if obj.file:
            assert_in_bible_dir(obj.file.path)  # raises SuspiciousFileOperation -> 400
        name = obj.name
        obj.delete()  # django-cleanup deletes the file from disk
        messages.success(request, f"{name} deleted.")
        return redirect("bible:list")
