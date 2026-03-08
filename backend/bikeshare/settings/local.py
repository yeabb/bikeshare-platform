from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

MQTT_BROKER_TYPE = "local"
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")  # noqa: F405
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))  # noqa: F405
