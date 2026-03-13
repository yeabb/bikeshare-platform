from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stations.models import Station, StationStatus
from apps.stations.serializers import InactiveStationSerializer, StationStateSerializer
from apps.stations.services import station_heartbeat_check


class StationStateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, station_id):
        try:
            station = Station.objects.prefetch_related(
                "docks__current_bike"
            ).get(id=station_id)
        except Station.DoesNotExist:
            return Response({"error": "NOT_FOUND"}, status=404)

        return Response(StationStateSerializer(station).data)


class InactiveStationsView(APIView):
    """
    Ops endpoint — lists all stations currently marked INACTIVE.
    Used by on-call ops to see which stations need physical attention.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stations = Station.objects.filter(
            status=StationStatus.INACTIVE
        ).order_by("last_telemetry_at")
        return Response({
            "count": stations.count(),
            "stations": InactiveStationSerializer(stations, many=True).data,
        })


@csrf_exempt
@require_POST
def internal_heartbeat(request):
    """
    Internal endpoint called by the Lambda station heartbeat function.

    Runs one heartbeat pass: marks all ACTIVE stations that have not sent
    telemetry within the inactivity threshold as INACTIVE.

    Called by: infra/aws/lambdas/station_heartbeat/handler.py
    Protected by: X-Internal-Secret header
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != settings.INTERNAL_API_SECRET:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    marked_inactive = station_heartbeat_check()
    return JsonResponse({"marked_inactive": marked_inactive})
