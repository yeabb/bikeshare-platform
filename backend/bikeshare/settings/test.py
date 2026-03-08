from .base import *  # noqa: F401, F403

DEBUG = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable MQTT publish during tests — tests use direct service calls
MQTT_BROKER_TYPE = "local"
MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883
