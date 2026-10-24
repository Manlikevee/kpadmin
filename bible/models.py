from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db import models
from django.db.models.functions import Lower

BIBLE_DIR = "bible"


def bible_upload_to(instance, filename):
    # The stored name is derived from the validated version name, never from the
    # client-supplied filename, so path tricks in the upload name are irrelevant.
    return f"{BIBLE_DIR}/{instance.name.upper()}_bible.json"


def assert_in_bible_dir(path):
    """Refuse any file operation outside MEDIA_ROOT/bible."""
    root = (Path(settings.MEDIA_ROOT) / BIBLE_DIR).resolve()
    target = Path(path).resolve()
    if root != target and root not in target.parents:
        raise SuspiciousFileOperation("File is outside the Bible upload directory.")
    return target


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class BibleTranslation(models.Model):
    name = models.CharField(max_length=12, help_text="Short version code, e.g. KJV.")
    file = models.FileField(upload_to=bible_upload_to, max_length=200)
    size_in_bytes = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="uniq_bible_name_ci")]

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip().upper()
        if self.file and hasattr(self.file, "size"):
            try:
                self.size_in_bytes = self.file.size
            except (OSError, ValueError):
                pass
        super().save(*args, **kwargs)

    @property
    def size(self):
        return human_size(self.size_in_bytes)

    @property
    def file_name(self):
        return Path(self.file.name).name if self.file else ""

    @property
    def url(self):
        return self.file.url if self.file else ""

    def __str__(self):
        return self.name
