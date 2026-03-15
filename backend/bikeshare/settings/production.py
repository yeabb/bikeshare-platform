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

# Allow all hosts for now — ALB sits in front and handles routing.
# Tighten this to the ALB DNS name once the domain is confirmed.
ALLOWED_HOSTS = ["*"]

# Whitenoise serves static files (Django admin, DRF browsable API)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
] + MIDDLEWARE[1:]  # type: ignore[name-defined]  # noqa: F405

STATIC_ROOT = BASE_DIR / "staticfiles"  # type: ignore[name-defined]  # noqa: F405

# MQTT — always AWS in production
MQTT_BROKER_TYPE = "aws"
AWS_REGION = _require_env("AWS_REGION")
AWS_IOT_ENDPOINT = _require_env("AWS_IOT_ENDPOINT")
