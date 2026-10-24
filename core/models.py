from django.db import models


class SiteSettings(models.Model):
    """Single-row global settings (Super Admin only)."""

    church_name = models.CharField(max_length=120, default="KP Global")
    tagline = models.CharField(max_length=200, blank=True, default="Come as you are.")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    give_instructions = models.TextField(blank=True, help_text="Bank details or giving instructions shown on the Give page.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "site settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Site settings"
