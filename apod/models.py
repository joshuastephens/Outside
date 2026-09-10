"""Persistence for NASA APOD entries and their supplemental enrichment."""

import datetime

from django.db import models

# NASA's first Astronomy Picture of the Day. Earlier dates are always a 400.
FIRST_APOD_DATE = datetime.date(1995, 6, 16)


class APOD(models.Model):
    """One row per calendar date; `date` doubles as the cache key.

    Normalized columns cover the fields the API contract depends on, while
    `raw_response` retains NASA's complete untouched payload so nothing is lost
    to schema drift.
    """

    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    date = models.DateField(unique=True, db_index=True)
    title = models.CharField(max_length=500)
    explanation = models.TextField(blank=True)
    media_type = models.CharField(max_length=32)
    url = models.URLField(max_length=2000)

    # NASA omits these on some days -- nullable, never assumed present.
    hdurl = models.URLField(max_length=2000, blank=True, null=True)
    copyright = models.CharField(max_length=500, blank=True, null=True)

    raw_response = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "APOD"
        verbose_name_plural = "APODs"

    def __str__(self):
        return f"{self.date}: {self.title}"


class SupplementalInfo(models.Model):
    """Enrichment for an APOD from one external source.

    A separate table rather than columns on APOD so several providers can
    contribute to the same entry. A lookup that finds nothing is still stored,
    with `status` and `reason` recording why -- the absence of a result is
    itself a result worth caching.
    """

    class Status(models.TextChoices):
        FOUND = "found", "Found"
        NOT_FOUND = "not_found", "Not found"
        ERROR = "error", "Error"

    apod = models.ForeignKey(
        APOD, related_name="supplemental", on_delete=models.CASCADE
    )
    source = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.NOT_FOUND
    )

    matched_title = models.CharField(max_length=500, blank=True, null=True)
    url = models.URLField(max_length=2000, blank=True, null=True)
    extract = models.TextField(blank=True)
    reason = models.TextField(blank=True)

    raw_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One current result per source per APOD; refreshes update in place.
        constraints = [
            models.UniqueConstraint(
                fields=["apod", "source"], name="unique_supplemental_per_source"
            )
        ]
        ordering = ["source"]
        verbose_name = "supplemental info"
        verbose_name_plural = "supplemental info"

    def __str__(self):
        return f"{self.source} ({self.status}) for {self.apod.date}"
