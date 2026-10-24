from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User


@receiver(post_save, sender=User, dispatch_uid="accounts_create_profile")
def create_profile(sender, instance, created, raw=False, **kwargs):
    """Create exactly one Profile per user. ``get_or_create`` makes this idempotent."""
    if raw:
        return
    Profile.objects.get_or_create(user=instance)
