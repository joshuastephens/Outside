"""Shared test scaffolding."""

import datetime
from unittest import mock

from django.test import TestCase

APOD_URL = "/api/apod/"

# A past date, so it stays valid however long from now the suite is run.
SAMPLE_DATE = datetime.date(2024, 5, 1)


class NoNetworkTestCase(TestCase):
    """A `TestCase` that fails loudly if anything reaches for the network.

    Every outbound call in this project goes through `requests`, which routes
    all verbs through `Session.request`. Blocking that one seam guarantees no
    test can quietly hit the real NASA or Wikipedia APIs.
    """

    def setUp(self):
        super().setUp()
        patcher = mock.patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError(
                "A test attempted a real HTTP request. Mock the client or "
                "provider instead."
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_apod(self, date=None):
        """GET the endpoint, forcing the JSON renderer."""
        params = {} if date is None else {"date": date}
        return self.client.get(APOD_URL, params, HTTP_ACCEPT="application/json")
