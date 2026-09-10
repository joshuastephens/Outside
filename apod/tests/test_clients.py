"""NASA client: how each upstream response shape is translated."""

import datetime

import requests

from apod.clients import NasaAPODClient, NasaAPODUnavailable, NasaClientError

from .base import SAMPLE_DATE, NoNetworkTestCase
from .fixtures import image_payload


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text="", raise_on_json=False):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("Expecting value")
        return self._json_body


class FakeSession:
    """Stands in for the `requests` module (or a `Session`)."""

    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.exception is not None:
            raise self.exception
        return self.response


class NasaAPODClientTests(NoNetworkTestCase):
    def client_with(self, **kwargs):
        session = FakeSession(**kwargs)
        client = NasaAPODClient(api_key="test-key", session=session)
        return client, session

    def test_successful_fetch_returns_payload(self):
        payload = image_payload()
        client, session = self.client_with(response=FakeResponse(json_body=payload))

        self.assertEqual(client.fetch(SAMPLE_DATE), payload)

    def test_sends_api_key_and_date(self):
        client, session = self.client_with(
            response=FakeResponse(json_body=image_payload())
        )
        client.fetch(datetime.date(2024, 5, 1))

        params = session.calls[0]["params"]
        self.assertEqual(params["api_key"], "test-key")
        self.assertEqual(params["date"], "2024-05-01")

    def test_404_raises_unavailable(self):
        client, _ = self.client_with(
            response=FakeResponse(
                status_code=404, json_body={"msg": "No data available for date."}
            )
        )
        with self.assertRaises(NasaAPODUnavailable):
            client.fetch(SAMPLE_DATE)

    def test_400_saying_no_data_raises_unavailable(self):
        client, _ = self.client_with(
            response=FakeResponse(
                status_code=400,
                json_body={"msg": "No data available for date: 2030-01-01"},
            )
        )
        with self.assertRaises(NasaAPODUnavailable):
            client.fetch(SAMPLE_DATE)

    def test_other_400_raises_client_error(self):
        client, _ = self.client_with(
            response=FakeResponse(status_code=400, json_body={"msg": "Bad Request"})
        )
        with self.assertRaises(NasaClientError):
            client.fetch(SAMPLE_DATE)

    def test_rate_limit_raises_client_error(self):
        client, _ = self.client_with(
            response=FakeResponse(
                status_code=429, json_body={"error": {"message": "Too many requests"}}
            )
        )
        with self.assertRaisesMessage(NasaClientError, "rate limit"):
            client.fetch(SAMPLE_DATE)

    def test_server_error_raises_client_error(self):
        client, _ = self.client_with(
            response=FakeResponse(status_code=503, text="Service Unavailable")
        )
        with self.assertRaises(NasaClientError):
            client.fetch(SAMPLE_DATE)

    def test_non_json_success_raises_client_error(self):
        client, _ = self.client_with(response=FakeResponse(raise_on_json=True))
        with self.assertRaises(NasaClientError):
            client.fetch(SAMPLE_DATE)

    def test_unexpected_payload_shape_raises_client_error(self):
        client, _ = self.client_with(response=FakeResponse(json_body=["not", "a dict"]))
        with self.assertRaises(NasaClientError):
            client.fetch(SAMPLE_DATE)

    def test_transport_failure_raises_client_error(self):
        client, _ = self.client_with(exception=requests.ConnectionError("reset"))
        with self.assertRaises(NasaClientError):
            client.fetch(SAMPLE_DATE)
