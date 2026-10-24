from django.contrib import admin

from .models import BibleTranslation


@admin.register(BibleTranslation)
class BibleTranslationAdmin(admin.ModelAdmin):
    list_display = ("name", "size_in_bytes", "updated_at")
    readonly_fields = ("size_in_bytes",)
