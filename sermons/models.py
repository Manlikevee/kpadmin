from django.db import models


class SermonNote(models.Model):
    """Local metadata layered over a YouTube video (YouTube stays the source of truth)."""

    video_id = models.CharField(max_length=20, unique=True)
    speaker = models.CharField(max_length=120, blank=True)
    series = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    is_featured = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False, help_text="Hide this video from the website and app.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.video_id
