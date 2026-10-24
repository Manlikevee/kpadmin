import json
import re

from django import forms
from django.conf import settings

from .models import BibleTranslation

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}$")


def validate_bible_json(upload):
    """Extension, size, UTF-8 and JSON-syntax checks. Leaves the file pointer at 0."""
    max_bytes = settings.BIBLE_MAX_UPLOAD_MB * 1024 * 1024
    if not upload.name.lower().endswith(".json"):
        raise forms.ValidationError("Please choose a .json file.")
    if upload.size == 0:
        raise forms.ValidationError("The file is empty.")
    if upload.size > max_bytes:
        raise forms.ValidationError(f"File is larger than {settings.BIBLE_MAX_UPLOAD_MB} MB.")
    try:
        data = json.loads(upload.read().decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise forms.ValidationError("The file must be UTF-8 text.")
    except ValueError as exc:
        raise forms.ValidationError(f"Invalid JSON: {exc}")
    finally:
        upload.seek(0)
    if not isinstance(data, (dict, list)) or not data:
        raise forms.ValidationError("The JSON must be a non-empty object or array.")
    return upload


class BibleUploadForm(forms.Form):
    name = forms.CharField(max_length=12)
    file = forms.FileField()

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not NAME_RE.match(name):
            raise forms.ValidationError("Use letters, numbers, - or _ only (up to 12 characters).")
        qs = BibleTranslation.objects.filter(name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"{name.upper()} already exists. Replace it instead.")
        return name.upper()

    def clean_file(self):
        return validate_bible_json(self.cleaned_data["file"])
