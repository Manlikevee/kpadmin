"""Small CRUD toolkit for the dashboards.

Every object lookup goes through ``get_scoped_queryset`` so a branch admin can
never read or change another branch's data, even by guessing ids.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.access import can_manage_branch, scope_to_branches
from accounts.mixins import RoleRequiredMixin


class ManagedMixin(RoleRequiredMixin):
    allowed_roles = ("branch_admin",)
    model = None
    page_id = ""
    super_only = False        # only super admins may use this section
    branch_field = "branch"   # None for global models
    include_global = False    # branch admins can also *see* rows with no branch (read-only)

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_super_admin:
            return True
        return user.is_branch_admin and not self.super_only

    def base_queryset(self):
        return self.model.objects.all()

    def get_scoped_queryset(self):
        qs = self.base_queryset()
        if self.branch_field is None:
            return qs
        return scope_to_branches(qs, self.request.user, self.branch_field, include_global=self.include_global)

    def can_edit(self, obj):
        user = self.request.user
        if user.is_super_admin:
            return True
        if self.super_only or self.branch_field is None:
            return False
        return can_manage_branch(user, getattr(obj, f"{self.branch_field}_id"))


class ManagedListView(ManagedMixin, ListView):
    def get_queryset(self):
        return self.get_scoped_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_id"] = self.page_id
        return ctx


class ManagedDetailView(ManagedMixin, DetailView):
    def get_queryset(self):
        return self.get_scoped_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(page_id=self.page_id, can_edit=self.can_edit(self.object))
        return ctx


class ManagedFormView(ManagedMixin, View):
    form_class = None
    template_name = ""
    list_url = ""
    detail_url = ""
    success_message = "Saved."
    delete_url_name = ""
    owner_field = None  # e.g. "created_by" / "author" set on create

    def get_object(self):
        pk = self.kwargs.get("pk")
        if not pk:
            return None
        obj = get_object_or_404(self.get_scoped_queryset(), pk=pk)
        if not self.can_edit(obj):
            raise PermissionDenied
        return obj

    def get_form(self, data=None, files=None, instance=None):
        return self.form_class(data, files, instance=instance, user=self.request.user)

    def render_form(self, form, obj):
        from django.urls import reverse

        delete_url = reverse(self.delete_url_name, args=[obj.pk]) if obj and self.delete_url_name else ""
        return render(self.request, self.template_name, {"form": form, "object": obj, "page_id": self.page_id,
                                                         "list_url": self.list_url, "delete_url": delete_url})

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        return self.render_form(self.get_form(instance=obj), obj)

    def before_save(self, obj, created):
        if created and self.owner_field and hasattr(obj, self.owner_field):
            setattr(obj, self.owner_field, self.request.user)

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        form = self.get_form(request.POST, request.FILES, instance=obj)
        if not form.is_valid():
            return self.render_form(form, obj)
        saved = form.save(commit=False)
        self.before_save(saved, created=obj is None)
        saved.save()
        form.save_m2m()
        messages.success(request, self.success_message)
        if self.detail_url:
            return redirect(self.detail_url, pk=saved.pk)
        return redirect(self.list_url)


class ManagedDeleteView(ManagedMixin, View):
    list_url = ""
    success_message = "Deleted."

    def post(self, request, pk):
        obj = get_object_or_404(self.get_scoped_queryset(), pk=pk)
        if not self.can_edit(obj):
            raise PermissionDenied
        obj.delete()
        messages.success(request, self.success_message)
        return redirect(self.list_url)

    def get(self, request, pk):  # deletion is POST-only
        raise Http404
