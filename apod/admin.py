from django.contrib import admin

from .models import APOD, SupplementalInfo


class SupplementalInfoInline(admin.TabularInline):
    model = SupplementalInfo
    extra = 0
    readonly_fields = ["source", "status", "matched_title", "url", "extract", "reason"]


@admin.register(APOD)
class APODAdmin(admin.ModelAdmin):
    list_display = ["date", "title", "media_type", "created_at"]
    list_filter = ["media_type"]
    search_fields = ["title", "explanation"]
    date_hierarchy = "date"
    inlines = [SupplementalInfoInline]


@admin.register(SupplementalInfo)
class SupplementalInfoAdmin(admin.ModelAdmin):
    list_display = ["apod", "source", "status", "matched_title"]
    list_filter = ["source", "status"]
