"""Serializers for the APOD endpoint.

Both the cache-hit and cache-miss paths return through these, so the response
shape is identical either way.
"""

from rest_framework import serializers

from .models import APOD, SupplementalInfo


class SupplementalInfoSerializer(serializers.ModelSerializer):
    """One provider's contribution.

    `status` and `reason` are always present so a consumer can tell "we looked
    and found nothing" apart from "we never looked".
    """

    class Meta:
        model = SupplementalInfo
        fields = ["source", "status", "matched_title", "url", "extract", "reason"]
        read_only_fields = fields


class APODSerializer(serializers.ModelSerializer):
    """A stored APOD plus its supplemental enrichment.

    `raw_response` is NASA's complete, unmodified payload; the normalized fields
    above it are the stable contract.
    """

    supplemental = SupplementalInfoSerializer(many=True, read_only=True)

    class Meta:
        model = APOD
        fields = [
            "date",
            "title",
            "explanation",
            "media_type",
            "url",
            "hdurl",
            "copyright",
            "raw_response",
            "supplemental",
        ]
        read_only_fields = fields
