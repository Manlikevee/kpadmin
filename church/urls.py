from django.urls import path

from . import views as v

app_name = "church"

urlpatterns = [
    path("", v.home, name="home"),
    # dashboards (one per role)
    path("dashboard/", v.SuperDashboard.as_view(), name="dashboard"),
    path("branch-dashboard/", v.BranchDashboardView.as_view(), name="branch_dashboard"),
    path("branches/<int:pk>/dashboard/", v.BranchDashboardView.as_view(), name="branch_detail"),
    path("worker/", v.WorkerDashboard.as_view(), name="worker_dashboard"),
    path("member/", v.MemberDashboard.as_view(), name="member_dashboard"),
    path("my-notifications/", v.MyNotifications.as_view(), name="my_notifications"),
    # branches
    path("branches/", v.BranchList.as_view(), name="branches"),
    path("branches/save/", v.BranchSave.as_view(), name="branch_create"),
    path("branches/<int:pk>/save/", v.BranchSave.as_view(), name="branch_edit"),
    # members
    path("members/", v.MemberList.as_view(), name="members"),
    path("members/new/", v.MemberForm.as_view(), name="member_create"),
    path("members/<int:pk>/", v.MemberDetail.as_view(), name="member_detail"),
    path("members/<int:pk>/edit/", v.MemberForm.as_view(), name="member_edit"),
    path("members/<int:pk>/delete/", v.MemberDelete.as_view(), name="member_delete"),
    # workers + applications
    path("workers/", v.WorkersView.as_view(), name="workers"),
    path("workers/applications/", v.WorkersView.as_view(tab="apps"), name="applications"),
    path("workers/add/", v.WorkerAdd.as_view(), name="worker_add"),
    path("workers/<int:pk>/toggle/", v.WorkerToggle.as_view(), name="worker_toggle"),
    path("applications/<int:pk>/approve/", v.ApplicationDecision.as_view(action="approve"), name="application_approve"),
    path("applications/<int:pk>/reject/", v.ApplicationDecision.as_view(action="reject"), name="application_reject"),
    path("apply/", v.apply_worker, name="apply"),
    # ministries
    path("ministries/", v.MinistryList.as_view(), name="ministries"),
    path("ministries/new/", v.MinistryForm.as_view(), name="ministry_create"),
    path("ministries/<int:pk>/", v.MinistryDetail.as_view(), name="ministry_detail"),
    path("ministries/<int:pk>/edit/", v.MinistryForm.as_view(), name="ministry_edit"),
    path("ministries/<int:pk>/delete/", v.MinistryDelete.as_view(), name="ministry_delete"),
    # events
    path("events/", v.EventList.as_view(), name="events"),
    path("events/new/", v.EventForm.as_view(), name="event_create"),
    path("events/<int:pk>/", v.EventDetail.as_view(), name="event_detail"),
    path("events/<int:pk>/edit/", v.EventForm.as_view(), name="event_edit"),
    path("events/<int:pk>/delete/", v.EventDelete.as_view(), name="event_delete"),
    path("events/<int:pk>/cancel/", v.event_cancel, name="event_cancel"),
    # announcements
    path("announcements/", v.AnnouncementList.as_view(), name="announcements"),
    path("announcements/new/", v.AnnouncementForm.as_view(), name="announcement_create"),
    path("announcements/<int:pk>/", v.AnnouncementDetail.as_view(), name="announcement_detail"),
    path("announcements/<int:pk>/edit/", v.AnnouncementForm.as_view(), name="announcement_edit"),
    path("announcements/<int:pk>/delete/", v.AnnouncementDelete.as_view(), name="announcement_delete"),
    # devotionals
    path("devotionals/", v.DevotionalList.as_view(), name="devotionals"),
    path("devotionals/new/", v.DevotionalForm.as_view(), name="devotional_create"),
    path("devotionals/<int:pk>/", v.DevotionalDetail.as_view(), name="devotional_detail"),
    path("devotionals/<int:pk>/edit/", v.DevotionalForm.as_view(), name="devotional_edit"),
    path("devotionals/<int:pk>/delete/", v.DevotionalDelete.as_view(), name="devotional_delete"),
    # prayer + praise
    path("prayer-requests/", v.PrayerBoard.as_view(), name="prayer_requests"),
    path("prayer-requests/<int:pk>/", v.PrayerDetail.as_view(), name="prayer_detail"),
    path("prayer-requests/<int:pk>/update/", v.PrayerUpdate.as_view(), name="prayer_update"),
    path("praise-reports/", v.PraiseList.as_view(), name="praise_reports"),
    path("praise-reports/new/", v.PraiseForm.as_view(), name="praise_create"),
    path("praise-reports/<int:pk>/", v.PraiseDetail.as_view(), name="praise_detail"),
    path("praise-reports/<int:pk>/edit/", v.PraiseForm.as_view(), name="praise_edit"),
    path("praise-reports/<int:pk>/delete/", v.PraiseDelete.as_view(), name="praise_delete"),
    path("praise-reports/<int:pk>/approve/", v.PraiseDecision.as_view(status="published"), name="praise_approve"),
    path("praise-reports/<int:pk>/decline/", v.PraiseDecision.as_view(status="declined"), name="praise_decline"),
    # giving, stories, notifications, settings
    path("giving/", v.GivingList.as_view(), name="giving"),
    path("giving/new/", v.GivingForm.as_view(), name="giving_create"),
    path("giving/<int:pk>/edit/", v.GivingForm.as_view(), name="giving_edit"),
    path("giving/<int:pk>/delete/", v.GivingDelete.as_view(), name="giving_delete"),
    path("stories/", v.StoryList.as_view(), name="stories"),
    path("stories/new/", v.StoryForm.as_view(), name="story_create"),
    path("stories/<int:pk>/edit/", v.StoryForm.as_view(), name="story_edit"),
    path("stories/<int:pk>/delete/", v.StoryDelete.as_view(), name="story_delete"),
    path("notifications/", v.NotificationsAdmin.as_view(), name="notifications"),
    path("settings/", v.SettingsView.as_view(), name="settings"),
]
