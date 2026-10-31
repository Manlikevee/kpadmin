import django_filters as df

from django.db.models import Q

from church.models import (Announcement, Event, GivingRecord, Member, Ministry, PraiseReport, PrayerRequest,
                           WorkerApplication)


class EventFilter(df.FilterSet):
    date_from = df.DateTimeFilter(method="filter_date_from")
    date_to = df.DateTimeFilter(field_name="start_at", lookup_expr="lte")

    class Meta:
        model = Event
        fields = ("branch", "kind", "status", "date_from", "date_to")

    def filter_date_from(self, queryset, name, value):
        # Recurring services keep their first occurrence as start_at, which may
        # be in the past even though their next weekly/monthly occurrence is ahead.
        return queryset.filter(Q(start_at__gte=value) | (~Q(repeat=Event.Repeat.NONE) & Q(start_at__lt=value)))


class MemberFilter(df.FilterSet):
    class Meta:
        model = Member
        fields = ("branch", "status")


class ApplicationFilter(df.FilterSet):
    class Meta:
        model = WorkerApplication
        fields = ("branch", "status", "ministry")


class AnnouncementFilter(df.FilterSet):
    class Meta:
        model = Announcement
        fields = ("branch", "is_pinned")


class MinistryFilter(df.FilterSet):
    # ministries a person can pick for a branch: that branch's own + church-wide ones
    for_branch = df.NumberFilter(method="filter_for_branch")

    class Meta:
        model = Ministry
        fields = ("branch", "is_active", "for_branch")

    def filter_for_branch(self, queryset, name, value):
        return queryset.filter(Q(branch_id=value) | Q(branch__isnull=True))


class PrayerAdminFilter(df.FilterSet):
    unassigned = df.BooleanFilter(method="filter_unassigned")

    class Meta:
        model = PrayerRequest
        fields = ("status", "branch", "assigned_to", "is_public", "unassigned")

    def filter_unassigned(self, queryset, name, value):
        return queryset.filter(assigned_to__isnull=bool(value))


class PraiseFilter(df.FilterSet):
    class Meta:
        model = PraiseReport
        fields = ("status", "branch", "category")


class GivingFilter(df.FilterSet):
    given_from = df.DateFilter(field_name="given_on", lookup_expr="gte")
    given_to = df.DateFilter(field_name="given_on", lookup_expr="lte")

    class Meta:
        model = GivingRecord
        fields = ("branch", "fund", "currency", "given_from", "given_to")
