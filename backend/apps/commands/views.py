from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.commands.models import Command
from apps.commands.serializers import CommandSerializer
from apps.commands.services import create_unlock_command


class UnlockCommandView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        bike_id = request.data.get("bike_id")
        if not bike_id:
            return Response({"error": "MISSING_BIKE_ID"}, status=400)

        command, error_code = create_unlock_command(request.user, bike_id)

        if error_code:
            http_status = 409 if error_code in ("ACTIVE_RIDE_EXISTS", "PENDING_COMMAND_EXISTS") else 400
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
