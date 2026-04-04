import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CHAPA_API_URL = settings.CHAPA_API_URL


class ChapaError(Exception):
    """Raised when the Chapa API returns an error or is unreachable."""
    pass


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.CHAPA_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_payment(
    tx_ref: str,
    amount: Decimal,
    phone: str,
    callback_url: str,
    return_url: str,
) -> str:
    """
    Initialize a Chapa payment. Returns the checkout_url.
    Raises ChapaError on failure.

    Args:
        tx_ref: Unique transaction reference (we use TopUp UUID).
        amount: Amount in ETB.
        phone: User's phone number (for pre-filling Chapa's form).
        callback_url: URL Chapa will POST to when payment completes (our webhook).
        return_url: URL Chapa redirects the user to after payment (deep link into app).
    """
    payload = {
        "amount": str(amount),
        "currency": "ETB",
        "tx_ref": tx_ref,
        "callback_url": callback_url,
        "return_url": return_url,
        "customization": {
            "title": "Bikeshare Wallet Top-Up",
        },
    }

    # Phone is optional on Chapa's side but pre-fills the form
    if phone:
        payload["phone_number"] = phone

    try:
        response = requests.post(
            f"{CHAPA_API_URL}/transaction/initialize",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
    except requests.RequestException as e:
        logger.exception("Chapa initialize request failed for tx_ref=%s", tx_ref)
        raise ChapaError("Could not reach Chapa API") from e

    if not response.ok:
        logger.error(
            "Chapa initialize failed tx_ref=%s status=%s body=%s",
            tx_ref, response.status_code, response.text,
        )
        raise ChapaError(f"Chapa returned {response.status_code}")

    data = response.json()
    checkout_url = data.get("data", {}).get("checkout_url")
    if not checkout_url:
        logger.error("Chapa response missing checkout_url tx_ref=%s body=%s", tx_ref, data)
        raise ChapaError("Chapa response missing checkout_url")

    return checkout_url


def verify_transaction(tx_ref: str) -> bool:
    """
    Verify a transaction with Chapa. Returns True if payment is confirmed as 'success'.
    Raises ChapaError if the API is unreachable.
    """
    try:
        response = requests.get(
            f"{CHAPA_API_URL}/transaction/verify/{tx_ref}",
            headers=_headers(),
            timeout=10,
        )
    except requests.RequestException as e:
        logger.exception("Chapa verify request failed for tx_ref=%s", tx_ref)
        raise ChapaError("Could not reach Chapa API") from e

    if not response.ok:
        logger.error(
            "Chapa verify failed tx_ref=%s status=%s body=%s",
            tx_ref, response.status_code, response.text,
        )
        return False

    data = response.json()
    status = data.get("data", {}).get("status", "")
    return status == "success"
