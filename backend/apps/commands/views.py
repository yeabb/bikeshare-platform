from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.commands.models import Command
from apps.commands.serializers import CommandSerializer
from apps.commands.services import create_unlock_command, sweep_timed_out_commands


class UnlockCommandView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        bike_id = request.data.get("bike_id")
        if not bike_id:
            return Response({"error": "MISSING_BIKE_ID"}, status=400)

        command, error_code = create_unlock_command(request.user, bike_id)

        if error_code:
            if error_code in ("ACTIVE_RIDE_EXISTS", "PENDING_COMMAND_EXISTS"):
                http_status = 409
            elif error_code in ("INSUFFICIENT_BALANCE", "DEBT_THRESHOLD_EXCEEDED"):
                http_status = 402
            else:
                http_status = 400
            return Response({"error": error_code}, status=http_status)

        return Response(CommandSerializer(command).data, status=202)


class CommandDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, request_id):
        try:
            command = Command.objects.select_related(
                "station", "dock", "bike"
            ).get(request_id=request_id, user=request.user)
        except Command.DoesNotExist:
            return Response({"error": "NOT_FOUND"}, status=404)

        return Response(CommandSerializer(command).data)


@csrf_exempt
@require_POST
def internal_sweep(request):
    """
    Internal endpoint called by the Lambda timeout sweep function.

    Runs one sweep pass: marks all PENDING commands past expires_at as TIMEOUT
    and restores their docks to OCCUPIED.

    Called by: infra/aws/lambdas/timeout_sweep/handler.py
    Protected by: X-Internal-Secret header
    """
    secret = request.headers.get("X-Internal-Secret", "")
    if not secret or secret != settings.INTERNAL_API_SECRET:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    swept = sweep_timed_out_commands()
    return JsonResponse({"swept": swept})
