
from .services import unread_count


def dashboard_nav(request):
    """Server-side sidebar for the dashboards, built from the signed-in user's role."""

    user = request.user

    if not user.is_authenticated or not request.path.startswith(
        ("/portal", "/accounts/profile", "/accounts/password/change")
    ):
        return {}

    from .models import PrayerRequest, PraiseReport, WorkerApplication
    from accounts.access import branches_for

    unread = unread_count(user)

    # Shared navigation entry for Notes.
    notes_link = ("church:notes", "Notes", "file", None, "notes")

    if user.is_super_admin:
        role = "super"

        pending_prayers = PrayerRequest.objects.filter(
            status="pending"
        ).count()

        pending_praise = PraiseReport.objects.filter(
            status="pending"
        ).count()

        groups = [
            (
                "Overview",
                [
                    ("church:dashboard", "Dashboard", "dashboard", None, "dashboard"),
                ],
            ),
            (
                "Church management",
                [
                    ("church:branches", "Branches", "branch", None, "branches"),
                    ("church:members", "Members", "members", None, "members"),
                    ("church:workers", "Workers", "worker", None, "workers"),
                    (
                        "church:ministries",
                        "Departments & Ministries",
                        "ministries",
                        None,
                        "ministries",
                    ),
                    ("church:events", "Events & Services", "events", None, "events"),
                    (
                        "church:prayer_requests",
                        "Prayer Requests",
                        "prayer",
                        pending_prayers or None,
                        "prayer-requests",
                    ),
                    ("church:giving", "Giving & Offerings", "giving", None, "giving"),
                ],
            ),
            (
                "App content",
                [
                    (
                        "church:devotionals",
                        "Devotionals",
                        "bible",
                        None,
                        "bible-devotionals",
                    ),
                    ("bible:list", "Bible Management", "file", None, "bible-management"),
                    (
                        "sermons_admin:list",
                        "Sermons & Media",
                        "sermons",
                        None,
                        "sermons-media",
                    ),
                    (
                        "church:praise_reports",
                        "Praise Reports",
                        "praise",
                        pending_praise or None,
                        "praise-reports",
                    ),
                    ("church:stories", "Stories", "stories", None, "stories"),
                    (
                        "church:announcements",
                        "Announcements",
                        "announce",
                        None,
                        "announcements",
                    ),
                    notes_link,
                ],
            ),
            (
                "Communication",
                [
                    (
                        "church:notifications",
                        "Notifications",
                        "notify",
                        None,
                        "notifications",
                    ),
                    ("church:settings", "Settings", "settings", None, "settings"),
                ],
            ),
        ]

        sub, label = "Administration Portal", "Super admin"

    elif user.is_branch_admin:
        role = "branch"

        pending = WorkerApplication.objects.filter(
            status="pending",
            branch__in=branches_for(user),
        ).count()

        groups = [
            (
                "Overview",
                [
                    (
                        "church:branch_dashboard",
                        "Dashboard",
                        "dashboard",
                        None,
                        "branch-dashboard",
                    ),
                ],
            ),
            (
                "My branch",
                [
                    ("church:members", "Members", "members", None, "members"),
                    ("church:workers", "Workers", "worker", None, "workers"),
                    (
                        "church:applications",
                        "Worker Applications",
                        "clip",
                        pending or None,
                        "applications",
                    ),
                ],
            ),
            (
                "Content",
                [
                    ("church:events", "Events", "events", None, "events"),
                    (
                        "sermons_admin:list",
                        "Sermons & Media",
                        "sermons",
                        None,
                        "sermons-media",
                    ),
                    (
                        "church:announcements",
                        "Announcements",
                        "announce",
                        None,
                        "announcements",
                    ),
                    (
                        "church:notifications",
                        "Notifications",
                        "notify",
                        None,
                        "notifications",
                    ),
                    notes_link,
                ],
            ),
        ]

        sub, label = "Branch Admin Portal", "Branch admin"

    elif user.is_worker:
        role = "worker"

        groups = [
            (
                "Serve",
                [
                    (
                        "church:worker_dashboard",
                        "Dashboard",
                        "dashboard",
                        None,
                        "worker-dashboard",
                    ),
                    (
                        "church:my_notifications",
                        "Notifications",
                        "notify",
                        unread or None,
                        "my-notifications",
                    ),
                    notes_link,
                    ("accounts:profile", "My Profile", "user", None, "profile"),
                ],
            ),
        ]

        sub, label = "Worker Portal", "Worker"

    else:
        role = "member"

        groups = [
            (
                "Welcome",
                [
                    (
                        "church:member_dashboard",
                        "Home",
                        "home",
                        None,
                        "member-dashboard",
                    ),
                    (
                        "church:my_notifications",
                        "Notifications",
                        "notify",
                        unread or None,
                        "my-notifications",
                    ),
                    notes_link,
                ],
            ),
            (
                "Get involved",
                [
                    (
                        "church:apply",
                        "Apply to Become a Worker",
                        "worker",
                        None,
                        "apply-worker",
                    ),
                    ("accounts:profile", "My Profile", "user", None, "profile"),
                ],
            ),
        ]

        sub, label = "Member Portal", "Member"

    return {
        "dash_groups": groups,
        "dash_role": role,
        "dash_sub": sub,
        "dash_role_label": label,
        "dash_unread": unread,
    }
