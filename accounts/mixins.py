from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Server-side role check. Super admins always pass."""

    allowed_roles = ()

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.has_role(*self.allowed_roles)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()


class SuperAdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ()  # has_role() only passes super admins


class StaffRequiredMixin(RoleRequiredMixin):
    """Super admins and branch admins."""

    allowed_roles = ("branch_admin",)


class WorkerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("branch_admin", "worker")
