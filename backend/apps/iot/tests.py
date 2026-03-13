"""
Tests for the internal station-event endpoint.

This endpoint is called by the Lambda event ingestion function in production.
It is protected by a shared secret and calls handle_station_event() on valid requests.
"""
import json
from unittest.mock import call, patch

from django.test import TestCase, override_settings
from django.urls import reverse


VALID_SECRET = "test-secret-abc123"
ENDPOINT = "/internal/station-event/"


@override_settings(INTERNAL_API_SECRET=VALID_SECRET)
class InternalStationEventAuthTests(TestCase):
    """Endpoint rejects requests without a valid secret."""

    def test_missing_secret_returns_401(self):
        resp = self.client.post(
            ENDPOINT,
            data=json.dumps({"station_id": "S001", "payload": {"type": "BIKE_DOCKED"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_wrong_secret_returns_401(self):
        resp = self.client.post(
            ENDPOINT,
            data=json.dumps({"station_id": "S001", "payload": {"type": "BIKE_DOCKED"}}),
            content_type="application/json",
            headers={"X-Internal-Secret": "wrong-secret"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_get_method_not_allowed(self):
        resp = self.client.get(
            ENDPOINT,
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        self.assertEqual(resp.status_code, 405)


@override_settings(INTERNAL_API_SECRET=VALID_SECRET)
class InternalStationEventValidationTests(TestCase):
    """Endpoint validates the request body."""

    def _post(self, body):
        return self.client.post(
            ENDPOINT,
            data=json.dumps(body),
            content_type="application/json",
            headers={"X-Internal-Secret": VALID_SECRET},
        )

    def test_invalid_json_returns_400(self):
        resp = self.client.post(
            ENDPOINT,
            data="not-json",
            content_type="application/json",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_station_id_returns_400(self):
        resp = self._post({"payload": {"type": "BIKE_DOCKED"}})
        self.assertEqual(resp.status_code, 400)

    def test_missing_payload_returns_400(self):
        resp = self._post({"station_id": "S001"})
        self.assertEqual(resp.status_code, 400)


@override_settings(INTERNAL_API_SECRET=VALID_SECRET)
class InternalStationEventDispatchTests(TestCase):
    """Endpoint calls handle_station_event with the correct arguments."""

    def _post(self, body):
        return self.client.post(
            ENDPOINT,
            data=json.dumps(body),
            content_type="application/json",
            headers={"X-Internal-Secret": VALID_SECRET},
        )

    @patch("apps.iot.views.handle_station_event")
    def test_valid_event_calls_handler(self, mock_handler):
        payload = {"type": "BIKE_DOCKED", "bikeId": "B001", "dockId": 1, "ts": 1234567890}
        resp = self._post({"station_id": "S001", "payload": payload})

        self.assertEqual(resp.status_code, 200)
        mock_handler.assert_called_once_with("S001", payload)

    @patch("apps.iot.views.handle_station_event")
    def test_response_body_is_ok(self, mock_handler):
        payload = {"type": "UNLOCK_RESULT", "requestId": "req-1", "status": "SUCCESS"}
        resp = self._post({"station_id": "S002", "payload": payload})

        self.assertEqual(resp.json(), {"status": "ok"})

    @patch("apps.iot.views.handle_station_event")
    def test_station_id_passed_from_body_not_payload(self, mock_handler):
        # Lambda always puts station_id at the top level. Verify we use that,
        # not whatever stationId might be in the payload.
        payload = {"type": "BIKE_DOCKED", "stationId": "S999"}
        resp = self._post({"station_id": "S001", "payload": payload})

        self.assertEqual(resp.status_code, 200)
        mock_handler.assert_called_once_with("S001", payload)
