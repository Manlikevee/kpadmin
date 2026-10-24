from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm

from .models import Profile

User = get_user_model()


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField()
    phone = forms.CharField(max_length=24, required=False)
    branch = forms.ModelChoiceField(queryset=None, required=False, empty_label="I'm not sure yet", label="Your branch")

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from church.models import Branch

        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)
        self.fields.pop("username", None)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        from .services import create_member_account

        d = self.cleaned_data
        return create_member_account(
            email=d["email"], password=d["password1"], first_name=d["first_name"],
            last_name=d["last_name"], phone=d.get("phone", ""), branch=d.get("branch"))


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ("phone", "image", "bio")


class StyledPasswordChangeForm(PasswordChangeForm):
    pass
