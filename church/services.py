"""Business logic shared by website views and the mobile API."""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.access import can_manage_branch, member_branch_ids

from .models import (Member, Notification, NotificationRead, WorkerApplication,
                     WorkerAssignment)


class ApplicationError(Exception):
    """Raised for rule violations (shown to the user as a message / API 400)."""


def ensure_member(user, branch=None, phone=""):
    """Create or update the single Member record for a user (no duplicates)."""
    member, created = Member.objects.get_or_create(
        user=user,
        defaults={
            "full_name": user.display_name,
            "email": user.email,
            "phone": phone,
            "branch": branch,
            "status": Member.Status.ACTIVE,
        },
    )
    if not created and branch and member.branch_id is None:
        member.branch = branch
        member.save(update_fields=["branch", "updated_at"])
    return member


def submit_worker_application(user, branch, ministry=None, experience="", availability=""):
    if user.is_worker and WorkerAssignment.objects.filter(user=user, branch=branch, is_active=True).exists():
        raise ApplicationError("You already serve as a worker in this branch.")
    if not branch.is_active:
        raise ApplicationError("This branch is not accepting applications.")
    if ministry is not None and ministry.branch_id not in (None, branch.pk):
        raise ApplicationError("That ministry does not belong to the chosen branch.")
    if WorkerApplication.objects.filter(applicant=user, branch=branch, status=WorkerApplication.Status.PENDING).exists():
        raise ApplicationError("You already have a pending application for this branch.")
    return WorkerApplication.objects.create(
        applicant=user, branch=branch, ministry=ministry, experience=experience, availability=availability
    )


def _notify(user, title, message):
    return Notification.objects.create(
        title=title[:80], message=message[:140], audience=Notification.Audience.USER, recipient=user
    )


@transaction.atomic
def approve_application(application, reviewer, note=""):
    """Approve and create/update the worker assignment without duplicating records."""
    application = WorkerApplication.objects.select_for_update().get(pk=application.pk)
    if not can_manage_branch(reviewer, application.branch_id):
        raise PermissionError("You cannot review applications for this branch.")
    if application.status != WorkerApplication.Status.PENDING:
        raise ApplicationError("This application has already been reviewed.")

    assignment, created = WorkerAssignment.objects.get_or_create(
        user=application.applicant, branch=application.branch, ministry=application.ministry,
        defaults={"is_active": True},
    )
    if not created and not assignment.is_active:
        assignment.is_active = True
        assignment.save(update_fields=["is_active", "updated_at"])

    applicant = application.applicant
    if applicant.role == applicant.Role.MEMBER:
        applicant.role = applicant.Role.WORKER
        applicant.save(update_fields=["role"])
    ensure_member(applicant, application.branch)

    application.status = WorkerApplication.Status.APPROVED
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.review_note = note
    application.save()
    _notify(applicant, "Worker application approved",
            f"You're now a worker at {application.branch.name}. Thank you for serving!")
    return assignment


@transaction.atomic
def reject_application(application, reviewer, note=""):
    application = WorkerApplication.objects.select_for_update().get(pk=application.pk)
    if not can_manage_branch(reviewer, application.branch_id):
        raise PermissionError("You cannot review applications for this branch.")
    if application.status != WorkerApplication.Status.PENDING:
        raise ApplicationError("This application has already been reviewed.")
    application.status = WorkerApplication.Status.REJECTED
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.review_note = note
    application.save()
    _notify(application.applicant, "Worker application update",
            f"Your application to {application.branch.name} was not approved this time.")
    return application


def notifications_for(user):
    """Notifications that have been sent and are addressed to this user."""
    q = Q(audience=Notification.Audience.ALL) | Q(recipient=user)
    branch_ids = member_branch_ids(user)
    if branch_ids:
        q |= Q(audience=Notification.Audience.BRANCH, branch_id__in=branch_ids)
    if user.is_worker or user.is_branch_admin or user.is_super_admin:
        q |= Q(audience=Notification.Audience.WORKERS) & (Q(branch__isnull=True) | Q(branch_id__in=branch_ids))
    return Notification.objects.filter(q, send_at__lte=timezone.now()).distinct()


def unread_count(user):
    if not user.is_authenticated:
        return 0
    read = NotificationRead.objects.filter(user=user).values("notification_id")
    return notifications_for(user).exclude(pk__in=read).count()


def mark_notifications_read(user, notifications=None):
    notifications = notifications if notifications is not None else notifications_for(user)
    existing = set(NotificationRead.objects.filter(user=user).values_list("notification_id", flat=True))
    NotificationRead.objects.bulk_create(
        [NotificationRead(notification=n, user=user) for n in notifications if n.pk not in existing],
        ignore_conflicts=True,
    )


def visible_events_q(user=None):
    """Public events: confirmed only. Branch filter applied by callers."""
    return Q(status="confirmed")


def sync_branch_admin_roles(branch, previous_admin_ids=()):
    """Keep ``User.role`` in step with ``Branch.admins``.

    Used by both the dashboard form and the API so assigning someone as a branch
    admin always promotes them, and removing their last branch demotes them.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    current = set(branch.admins.values_list("pk", flat=True))
    for user in User.objects.filter(pk__in=current, role__in=[User.Role.MEMBER, User.Role.WORKER]):
        user.role = User.Role.BRANCH_ADMIN
        user.save(update_fields=["role"])
    for user in User.objects.filter(pk__in=set(previous_admin_ids) - current, role=User.Role.BRANCH_ADMIN):
        if not user.managed_branches.exists():  # no longer manages anything
            has_assignment = user.worker_assignments.filter(is_active=True).exists()
            user.role = User.Role.WORKER if has_assignment else User.Role.MEMBER
            user.save(update_fields=["role"])
