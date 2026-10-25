
import os

from django.conf import settings
from django.db import models
from cloudinary_storage.storage import RawMediaCloudinaryStorage


def bible_upload_to(instance, filename):
    """
    Store Bible translation JSON files in the Cloudinary bible folder.
    Example: bible/KJV_bible.json
    """
    version_name = instance.name.strip().upper()
    return f"bible/{version_name}_bible.json"


def human_size(size_in_bytes):
    """Convert a file size in bytes into a human-readable format."""
    if size_in_bytes is None or size_in_bytes < 0:
        size_in_bytes = 0

    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"

    if size_in_bytes < 1024**2:
        return f"{size_in_bytes / 1024:.2f} KB"

    if size_in_bytes < 1024**3:
        return f"{size_in_bytes / (1024**2):.2f} MB"

    return f"{size_in_bytes / (1024**3):.2f} GB"


class BibleTranslation(models.Model):
    name = models.CharField(
        max_length=50,
        unique=True,
        help_text="Bible translation name, e.g. KJV, NIV, ESV.",
    )

    file = models.FileField(
        upload_to=bible_upload_to,
        storage=RawMediaCloudinaryStorage(),
        max_length=200,
        help_text="Upload the Bible translation JSON file.",
    )

    size_in_bytes = models.PositiveBigIntegerField(
        default=0,
        editable=False,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bible_translations",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Bible Translation"
        verbose_name_plural = "Bible Translations"
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"),
                name="unique_bible_translation_name_case_insensitive",
            )
        ]

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip().upper()

        # Do not call self.file.size here.
        # Cloudinary storage may raise KeyError if its response
        # does not contain a content-length header.
        super().save(*args, **kwargs)

    @property
    def size(self):
        """Return a human-readable file size."""
        return human_size(self.size_in_bytes)

    @property
    def file_name(self):
        """Return the uploaded file's name."""
        return os.path.basename(self.file.name) if self.file else None

    @property
    def url(self):
        """Return the file URL when available."""
        if self.file:
            try:
                return self.file.url
            except (ValueError, OSError):
                return None

        return None

    def __str__(self):
        return self.name
