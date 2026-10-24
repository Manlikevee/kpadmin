"""Public website views (standard Django views + templates)."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from church.models import Branch, Devotional, Event, Ministry, PraiseReport
from sermons.views import overlay_notes
from sermons.youtube import get_service

from .forms import ContactForm, PublicPrayerForm, PublicPraiseForm, VisitForm


def public_events():
    return Event.objects.filter(status="confirmed").select_related("branch")


def todays_devotional():
    return Devotional.objects.filter(is_published=True, date__lte=timezone.localdate()).first()


class Page(TemplateView):
    nav = ""

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["nav"] = self.nav
        return ctx


class HomeView(Page):
    template_name = "website/index.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        sermons = overlay_notes(get_service().get_sermons(page_size=4)["items"])
        ctx.update(
            sermons=sermons,
            events=public_events().filter(start_at__gte=timezone.now())[:4],
            devotional=todays_devotional(),
            praise=PraiseReport.objects.filter(status="published")[:3],
            branches=Branch.objects.filter(is_active=True)[:3],
            branch_total=Branch.objects.filter(is_active=True).count(),
        )
        return ctx


class AboutView(Page):
    template_name = "website/about.html"
    nav = "about"


class GalleryView(Page):
    template_name = "website/gallery.html"
    nav = "gallery"


class GiveView(Page):
    template_name = "website/give.html"


class LocationsView(Page):
    template_name = "website/locations.html"
    nav = "locations"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["branches"] = Branch.objects.filter(is_active=True)
        return ctx


class MinistriesView(Page):
    template_name = "website/ministries.html"
    nav = "ministries"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["ministries"] = Ministry.objects.filter(is_active=True).select_related("branch")
        return ctx


class EventsView(Page):
    template_name = "website/events.html"
    nav = "events"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        branch = self.request.GET.get("branch")
        events = public_events().filter(start_at__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
        if branch and branch.isdigit():
            events = events.filter(branch_id=branch) | events.filter(branch__isnull=True, start_at__gte=timezone.now())
        ctx.update(events=events.order_by("start_at"), branches=Branch.objects.filter(is_active=True),
                   branch_filter=branch or "",
                   weekly=public_events().filter(repeat="weekly")[:6])
        return ctx


def event_detail(request, pk):
    event = get_object_or_404(public_events(), pk=pk)
    others = public_events().filter(start_at__gte=timezone.now()).exclude(pk=pk)[:3]
    return render(request, "website/event.html", {"event": event, "others": others, "nav": "events"})


class DevotionalsView(Page):
    template_name = "website/devotionals.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        today = todays_devotional()
        ctx.update(today=today,
                   archive=Devotional.objects.filter(is_published=True, date__lte=timezone.localdate())
                   .exclude(pk=today.pk if today else None)[:12])
        return ctx


class FormPage(View):
    """Public form -> save -> message -> redirect (post/redirect/get)."""

    template_name = ""
    form_class = None
    success_message = "Thank you!"
    success_url = ""
    nav = ""
    extra = None

    def get_form(self, data=None):
        return self.form_class(data)

    def ctx(self, form):
        return {"form": form, "nav": self.nav, **(self.extra() if self.extra else {})}

    def get(self, request):
        return render(request, self.template_name, self.ctx(self.get_form()))

    def save(self, request, form):
        obj = form.save(commit=False)
        self.prepare(request, obj)
        obj.save()
        return obj

    def prepare(self, request, obj):
        pass

    def post(self, request):
        form = self.get_form(request.POST)
        if form.is_valid():
            self.save(request, form)
            messages.success(request, self.success_message)
            return redirect(self.success_url)
        return render(request, self.template_name, self.ctx(form))


class ContactView(FormPage):
    template_name = "website/contact.html"
    form_class = ContactForm
    success_message = "Thanks for reaching out. We'll get back to you soon."
    success_url = "core:contact"
    nav = "contact"


class NewHereView(FormPage):
    template_name = "website/new-here.html"
    form_class = VisitForm
    success_message = "We can't wait to meet you! Someone from the church will be in touch."
    success_url = "core:new_here"

    def prepare(self, request, obj):
        obj.kind = "visit"
        obj.subject = "Plan a visit"


class PrayerView(FormPage):
    template_name = "website/prayer.html"
    form_class = PublicPrayerForm
    success_message = "Your request has been received. Our prayer team is standing with you."
    success_url = "core:prayer"

    def prepare(self, request, obj):
        if request.user.is_authenticated:
            obj.user = request.user
            obj.name = obj.name or request.user.display_name


class PraiseView(FormPage):
    template_name = "website/praise.html"
    form_class = PublicPraiseForm
    success_message = "Thank you for sharing! Your praise report will appear once it has been reviewed."
    success_url = "core:praise"

    def extra(self):
        return {"reports": PraiseReport.objects.filter(status="published")[:12]}

    def prepare(self, request, obj):
        if request.user.is_authenticated:
            obj.user = request.user
            obj.name = obj.name or request.user.display_name


def subscribe(request):
    """Footer newsletter form: stores the address once (no duplicates)."""
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    from church.models import ContactMessage

    if request.method != "POST":
        return redirect("core:home")
    email = (request.POST.get("email") or "").strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Please enter a valid email address.")
    else:
        ContactMessage.objects.get_or_create(kind="subscribe", email=email, defaults={"name": "Subscriber"})
        messages.success(request, "Thanks for subscribing!")
    target = request.META.get("HTTP_REFERER", "")
    from django.utils.http import url_has_allowed_host_and_scheme
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("core:home")
