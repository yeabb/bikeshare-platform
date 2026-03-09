"""
MQTT publisher for station commands.

Local dev:  publishes to Mosquitto via paho-mqtt
Production: publishes to AWS IoT Core via boto3

Controlled by settings.MQTT_BROKER_TYPE = "local" | "aws"
"""
import json
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def publish_unlock_command(command) -> timezone.datetime:
    """
    Publish an UNLOCK command payload to the station's command topic.
    Returns the publish timestamp.
    """
    topic = f"station/{command.station_id}/cmd"
    payload = {
        "type": "UNLOCK",
        "requestId": str(command.request_id),
        "stationId": command.station_id,
        "dockId": command.dock.dock_index,
        "bikeId": command.bike_id,
        "userId": str(command.user.phone),
        "ttlSec": settings.COMMAND_TTL_SECONDS,
        "ts": int(timezone.now().timestamp()),
    }

    _publish(topic, payload)
    return timezone.now()


def _publish(topic: str, payload: dict) -> None:
    broker_type = settings.MQTT_BROKER_TYPE

    if broker_type == "local":
        _publish_local(topic, payload)
    elif broker_type == "aws":
        _publish_aws(topic, payload)
    else:
        raise ValueError(f"Unknown MQTT_BROKER_TYPE: {broker_type}")


def _publish_local(topic: str, payload: dict) -> None:
    """Publish via Mosquitto using paho-mqtt."""
    import paho.mqtt.publish as mqtt_publish

    mqtt_publish.single(
        topic,
        payload=json.dumps(payload),
        hostname=settings.MQTT_BROKER_HOST,
        port=settings.MQTT_BROKER_PORT,
        qos=1,
    )
    logger.debug(f"[MQTT local] → {topic}: {payload}")


def _publish_aws(topic: str, payload: dict) -> None:
    """Publish via AWS IoT Core using boto3."""
    import boto3

    client = boto3.client(
        "iot-data",
        region_name=settings.AWS_REGION,
        endpoint_url=f"https://{settings.AWS_IOT_ENDPOINT}",
    )
    client.publish(
        topic=topic,
        qos=1,
        payload=json.dumps(payload),
    )
    logger.debug(f"[MQTT aws] → {topic}: {payload}")
