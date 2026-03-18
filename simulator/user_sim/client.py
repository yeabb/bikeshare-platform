"""
HTTP API client for the bikeshare backend.

Wraps each API call the user simulator makes. Knows nothing about threading
or fleet config — just how to talk to the backend.
"""
import logging

import requests

logger = logging.getLogger(__name__)


class BikeShareClient:
    def __init__(self, base_url: str, phone: str):
        self.base_url = base_url.rstrip("/")
        self.phone = phone
        self._token: str | None = None

    def authenticate(self) -> None:
        """Request OTP and verify it to get a JWT access token.

        In DEBUG mode the backend returns the OTP directly in the response,
        so no SMS is needed for local dev.
        """
        resp = requests.post(
            f"{self.base_url}/api/v1/auth/request-otp/",
            json={"phone": self.phone},
        )
        resp.raise_for_status()
        otp = resp.json()["otp"]

        resp = requests.post(
            f"{self.base_url}/api/v1/auth/verify-otp/",
            json={"phone": self.phone, "otp": otp},
        )
        resp.raise_for_status()
        self._token = resp.json()["access"]
        logger.debug(f"[{self.phone}] Authenticated")

    def unlock(self, bike_id: str) -> str:
        """POST /api/v1/commands/unlock. Returns the request_id (UUID string)."""
        resp = requests.post(
            f"{self.base_url}/api/v1/commands/unlock",
            json={"bike_id": bike_id},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()["request_id"]

    def poll_command(self, request_id: str) -> dict:
        """GET /api/v1/commands/{request_id}. Returns the full command dict."""
        resp = requests.get(
            f"{self.base_url}/api/v1/commands/{request_id}",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def get_active_ride(self) -> dict | None:
        """GET /api/v1/me/active-ride. Returns the ride dict, or None if no active ride."""
        resp = requests.get(
            f"{self.base_url}/api/v1/me/active-ride",
            headers=self._auth_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def _auth_headers(self) -> dict:
        if not self._token:
            raise RuntimeError(f"[{self.phone}] Not authenticated — call authenticate() first")
        return {"Authorization": f"Bearer {self._token}"}
