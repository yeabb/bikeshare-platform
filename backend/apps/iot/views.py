"""
Internal views for the iot app.

These endpoints are NOT part of the public API. They are called by AWS Lambda
functions inside the VPC and are protected by a shared secret header.
"""
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.iot.event_handler import handle_station_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def internal_station_event(request):
    """
    Receive a station event forwarded by the Lambda event ingestion function.

    Called by: lambda/event_ingestion/handler.py
    Protected by: X-Internal-Secret header (shared secret, never a user JWT)

    Expected body:
        {
            "station_id": "S001",
            "payload": { ...MQTT event fields... }
        }
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != settings.INTERNAL_API_SECRET:
        logger.warning("Internal station-event request rejected — bad or missing secret")
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    station_id = data.get("station_id")
    payload = data.get("payload")

    if not station_id or payload is None:
        return JsonResponse({"error": "Missing station_id or payload"}, status=400)

    handle_station_event(station_id, payload)

    return JsonResponse({"status": "ok"})
