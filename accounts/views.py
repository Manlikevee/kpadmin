from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView

from .forms import ProfileForm, RegistrationForm, StyledPasswordChangeForm, UserEditForm


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "accounts/register.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("church:home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user, backend="accounts.backends.EmailOrUsernameBackend")
        messages.success(self.request, "Welcome to KP Global! Your account is ready.")
        return redirect("church:home")


class ProfileView(LoginRequiredMixin, View):
    """Members and workers manage their profile and associated member branch."""

    template_name = "accounts/profile.html"

    def _forms(self, request, data=None, files=None):
        return (
            UserEditForm(data, instance=request.user, prefix="u"),
            ProfileForm(data, files, instance=request.user.profile, prefix="p"),
        )

    def get(self, request):
        user_form, profile_form = self._forms(request)
        return render(request, self.template_name, {"user_form": user_form, "profile_form": profile_form})

    def post(self, request):
        old_email = request.user.email
        user_form, profile_form = self._forms(request, request.POST, request.FILES)
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save(commit=False)
            if user.username.lower() == old_email.lower():  # username followed the email; keep it that way
                user.username = user.email
            user.save()
            profile_form.save()
            from church.models import Member
            branch = profile_form.cleaned_data["branch"]
            member, created = Member.objects.get_or_create(
                user=user,
                defaults={"full_name": user.display_name, "email": user.email, "branch": branch},
            )
            if not created and member.branch_id != getattr(branch, "pk", None):
                member.branch = branch
                member.save(update_fields=["branch", "updated_at"])
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
        return render(request, self.template_name, {"user_form": user_form, "profile_form": profile_form})


class PasswordChange(LoginRequiredMixin, PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)
