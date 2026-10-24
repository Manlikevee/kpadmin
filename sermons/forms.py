from django import forms

from .models import SermonNote


class SermonNoteForm(forms.ModelForm):
    class Meta:
        model = SermonNote
        fields = ("speaker", "series", "notes", "is_featured", "is_hidden")
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}

    side_fields = ("is_featured", "is_hidden")

    @property
    def main_fields(self):
        return [self[n] for n in self.fields if n not in self.side_fields]

    @property
    def side_bound_fields(self):
        return [self[n] for n in self.side_fields]
