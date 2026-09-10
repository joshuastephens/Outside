"""(7) Serializer output: media URL, the full NASA payload, supplemental fields."""

from apod.models import APOD, SupplementalInfo
from apod.serializers import APODSerializer

from .base import SAMPLE_DATE, NoNetworkTestCase
from .fixtures import MINIMAL_PAYLOAD, image_payload


class APODSerializerTests(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self.payload = image_payload()
        self.apod = APOD.objects.create(
            date=SAMPLE_DATE,
            title=self.payload["title"],
            explanation=self.payload["explanation"],
            media_type=self.payload["media_type"],
            url=self.payload["url"],
            hdurl=self.payload["hdurl"],
            copyright=self.payload["copyright"],
            raw_response=self.payload,
        )
        SupplementalInfo.objects.create(
            apod=self.apod,
            source="wikipedia",
            status=SupplementalInfo.Status.FOUND,
            matched_title="Messier 101",
            url="https://en.wikipedia.org/wiki/Messier_101",
            extract="Messier 101 is a face-on spiral galaxy.",
        )

    def test_contains_the_media_url(self):
        data = APODSerializer(self.apod).data
        self.assertEqual(data["url"], self.payload["url"])
        self.assertEqual(data["hdurl"], self.payload["hdurl"])
        self.assertEqual(data["media_type"], "image")

    def test_contains_the_complete_nasa_payload(self):
        data = APODSerializer(self.apod).data
        self.assertEqual(data["raw_response"], self.payload)
        # Including fields with no normalized column of their own.
        self.assertEqual(data["raw_response"]["service_version"], "v1")

    def test_contains_supplemental_fields(self):
        data = APODSerializer(self.apod).data

        self.assertEqual(len(data["supplemental"]), 1)
        supplemental = data["supplemental"][0]
        self.assertEqual(
            set(supplemental),
            {"source", "status", "matched_title", "url", "extract", "reason"},
        )
        self.assertEqual(supplemental["source"], "wikipedia")
        self.assertEqual(supplemental["status"], "found")
        self.assertEqual(supplemental["matched_title"], "Messier 101")
        self.assertIn("spiral galaxy", supplemental["extract"])

    def test_top_level_shape_is_stable(self):
        data = APODSerializer(self.apod).data
        self.assertEqual(
            set(data),
            {
                "date",
                "title",
                "explanation",
                "media_type",
                "url",
                "hdurl",
                "copyright",
                "raw_response",
                "supplemental",
            },
        )

    def test_absent_optional_fields_serialize_as_null(self):
        apod = APOD.objects.create(
            date="2026-09-09",
            title=MINIMAL_PAYLOAD["title"],
            explanation=MINIMAL_PAYLOAD["explanation"],
            media_type="video",
            url=MINIMAL_PAYLOAD["url"],
            raw_response=MINIMAL_PAYLOAD,
        )
        data = APODSerializer(apod).data

        self.assertIsNone(data["hdurl"])
        self.assertIsNone(data["copyright"])
        self.assertEqual(data["supplemental"], [])
