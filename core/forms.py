from django import forms

from church.models import ContactMessage, PrayerRequest, PraiseReport

from .models import SiteSettings


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ("church_name", "tagline", "contact_email", "contact_phone", "address", "give_instructions")
        widgets = {"give_instructions": forms.Textarea(attrs={"rows": 4})}


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "phone", "subject", "message")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["message"].required = True


class VisitForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "phone", "branch", "message")
        labels = {"message": "Anything we should know? (optional)"}


class PublicPrayerForm(forms.ModelForm):
    class Meta:
        model = PrayerRequest
        fields = ("name", "email", "title", "request", "branch", "is_public")
        labels = {"request": "Your prayer request", "is_public": "Share with the prayer wall (public)"}


class PublicPraiseForm(forms.ModelForm):
    class Meta:
        model = PraiseReport
        fields = ("name", "category", "story", "branch")
