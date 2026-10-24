from django.contrib import admin

from . import models


@admin.register(models.Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "city", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "city")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("admins",)


@admin.register(models.Ministry)
class MinistryAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "leader", "is_active")
    list_filter = ("branch", "is_active")
    search_fields = ("name",)


@admin.register(models.Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "branch", "status", "joined_on")
    list_filter = ("branch", "status")
    search_fields = ("full_name", "email", "phone")


@admin.register(models.WorkerAssignment)
class WorkerAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "ministry", "is_active")
    list_filter = ("branch", "is_active")


@admin.register(models.WorkerApplication)
class WorkerApplicationAdmin(admin.ModelAdmin):
    list_display = ("applicant", "branch", "ministry", "status", "submitted_at", "reviewed_by")
    list_filter = ("status", "branch")
    readonly_fields = ("submitted_at",)


@admin.register(models.Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "branch", "kind", "start_at", "status")
    list_filter = ("status", "kind", "branch")
    search_fields = ("title",)


@admin.register(models.Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "branch", "is_published", "publish_at", "is_pinned")
    list_filter = ("is_published", "branch")


@admin.register(models.Devotional)
class DevotionalAdmin(admin.ModelAdmin):
    list_display = ("title", "scripture_ref", "date", "is_published")
    list_filter = ("is_published",)


@admin.register(models.Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "branch", "send_at")
    list_filter = ("audience",)


@admin.register(models.PrayerRequest)
class PrayerRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "author_name", "branch", "status", "is_public", "created_at")
    list_filter = ("status", "is_public", "branch")


@admin.register(models.PraiseReport)
class PraiseReportAdmin(admin.ModelAdmin):
    list_display = ("category", "author_name", "branch", "status", "created_at")
    list_filter = ("status", "branch")


@admin.register(models.GivingRecord)
class GivingRecordAdmin(admin.ModelAdmin):
    list_display = ("giver", "fund", "amount", "currency", "branch", "given_on")
    list_filter = ("fund", "branch")


@admin.register(models.Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("title", "branch", "is_published", "published_at")


@admin.register(models.ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "kind", "handled", "created_at")
    list_filter = ("kind", "handled")


admin.site.register(models.NotificationRead)
