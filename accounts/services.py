from django.contrib.auth import get_user_model
from django.db import transaction


@transaction.atomic
def create_member_account(*, email, password, first_name="", last_name="", phone="", branch=None):
    """Self-registration. Always creates a plain *member*: elevated roles can only be
    granted by administrators. Shared by the website form and the mobile API."""
    from church.services import ensure_member

    User = get_user_model()
    email = email.strip().lower()
    user = User(username=email, email=email, first_name=first_name, last_name=last_name, role=User.Role.MEMBER)
    user.set_password(password)
    user.save()  # post_save signal creates the Profile
    if phone:
        user.profile.phone = phone
        user.profile.save(update_fields=["phone", "updated_at"])
    ensure_member(user, branch, phone=phone)
    return user
