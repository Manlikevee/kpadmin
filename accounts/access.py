"""Server-side branch scoping shared by website views and API endpoints."""


def branches_for(user):
    """Branches this user may *manage* (super admin: all; branch admin: assigned)."""
    from church.models import Branch

    if not user or not user.is_authenticated:
        return Branch.objects.none()
    if user.is_super_admin:
        return Branch.objects.all()
    if user.is_branch_admin:
        return Branch.objects.filter(admins=user)
    return Branch.objects.none()


def can_manage_branch(user, branch):
    if branch is None:
        return bool(user and user.is_authenticated and user.is_super_admin)
    branch_id = getattr(branch, "pk", branch)
    return branches_for(user).filter(pk=branch_id).exists()


def member_branch_ids(user):
    """Branches the user belongs to as a member or serves in as a worker."""
    from church.models import Member, WorkerAssignment

    if not user or not user.is_authenticated:
        return set()
    ids = set(Member.objects.filter(user=user, branch__isnull=False).values_list("branch_id", flat=True))
    ids |= set(WorkerAssignment.objects.filter(user=user, is_active=True).values_list("branch_id", flat=True))
    return ids


def scope_to_branches(queryset, user, field="branch", include_global=False):
    """Limit ``queryset`` to branches the user manages (super admin sees everything)."""
    from django.db.models import Q

    if user.is_super_admin:
        return queryset
    ids = list(branches_for(user).values_list("pk", flat=True))
    q = Q(**{f"{field}__in": ids})
    if include_global:
        q |= Q(**{f"{field}__isnull": True})
    return queryset.filter(q)
