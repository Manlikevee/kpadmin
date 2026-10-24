import django_filters as df

from church.models import Announcement, Event, Member, WorkerApplication


class EventFilter(df.FilterSet):
    date_from = df.DateTimeFilter(field_name="start_at", lookup_expr="gte")
    date_to = df.DateTimeFilter(field_name="start_at", lookup_expr="lte")

    class Meta:
        model = Event
        fields = ("branch", "kind", "status", "date_from", "date_to")


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
