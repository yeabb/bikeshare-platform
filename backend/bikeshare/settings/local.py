from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5433")  # noqa: F405
DATABASES["default"]["PORT"] = POSTGRES_PORT  # noqa: F405

MQTT_BROKER_TYPE = "local"
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")  # noqa: F405
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        # App loggers — show INFO and above
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "mqtt_listener": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Django request errors only
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
