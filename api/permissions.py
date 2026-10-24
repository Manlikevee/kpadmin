from rest_framework import permissions

from accounts.access import can_manage_branch


class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_super_admin)


class IsStaffRole(permissions.BasePermission):
    """Super admins and branch admins."""

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_staff_role)


class ReadAnyWriteStaff(permissions.BasePermission):
    """Anyone may read; only staff may write; staff need rights over the object's branch."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        u = request.user
        return bool(u and u.is_authenticated and u.is_staff_role)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return can_manage_branch(request.user, getattr(obj, "branch_id", None))


class ReadAnyWriteSuper(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        u = request.user
        return bool(u and u.is_authenticated and u.is_super_admin)
