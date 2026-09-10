"""Shared test scaffolding."""

import datetime
import logging
from unittest import mock

from django.test import TestCase

APOD_URL = "/api/apod/"

# A past date, so it stays valid however long from now the suite is run.
SAMPLE_DATE = datetime.date(2024, 5, 1)


class _CapturingHandler(logging.Handler):
    """Collects records into a caller-supplied list instead of writing them."""

    def __init__(self, records):
        super().__init__()
        self.records = records

    def emit(self, record):
        self.records.append(record)


class QuietLogsMixin:
    """Capture log output for the duration of a test instead of printing it.

    This suite deliberately drives failure paths -- a provider that raises, a
    NASA timeout, a malformed date -- and the production code logs each one,
    correctly. Left alone that puts a stack trace in the middle of a passing
    run, which reads like a broken build to anyone running the suite for the
    first time.

    Records are captured, not discarded: `self.log_records` holds every one, so
    a test can still assert that something was logged. Nothing here touches the
    project's logging configuration, which stays exactly as it runs in
    production; only this process's handlers are swapped, and only while a test
    is executing.

    `assertLogs` still works inside a test -- it saves and restores whatever
    handlers it finds, including these.
    """

    # `django.request` logs every 4xx and 5xx the test client provokes.
    captured_loggers = ("apod", "django.request")

    def setUp(self):
        super().setUp()
        self.log_records = []
        handler = _CapturingHandler(self.log_records)

        for name in self.captured_loggers:
            logger = logging.getLogger(name)
            previous = (logger.handlers[:], logger.propagate, logger.level)
            logger.handlers = [handler]
            logger.propagate = False
            # Capture everything, so an assertion can look for any level.
            logger.setLevel(logging.DEBUG)
            self.addCleanup(self._restore_logger, logger, previous)

    @staticmethod
    def _restore_logger(logger, previous):
        logger.handlers, logger.propagate, logger.level = previous


class NoNetworkTestCase(QuietLogsMixin, TestCase):
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
