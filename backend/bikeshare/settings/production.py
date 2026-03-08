import os  # noqa: F811

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403


def _require_env(key: str) -> str:
    """Raise at startup if a required production env var is missing."""
    val = os.environ.get(key)
    if not val:
        raise ImproperlyConfigured(
            f"Environment variable '{key}' is required in production but is not set."
        )
    return val


DEBUG = False

ALLOWED_HOSTS = _require_env("ALLOWED_HOSTS").split(",")

# MQTT — always AWS in production
MQTT_BROKER_TYPE = "aws"
AWS_REGION = _require_env("AWS_REGION")
AWS_IOT_ENDPOINT = _require_env("AWS_IOT_ENDPOINT")
