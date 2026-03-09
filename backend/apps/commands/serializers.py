from rest_framework import serializers

from apps.commands.models import Command


class CommandSerializer(serializers.ModelSerializer):
    request_id = serializers.UUIDField()
    station_id = serializers.CharField()
    dock_index = serializers.IntegerField(source="dock.dock_index")
    bike_id = serializers.CharField(allow_null=True)
    # ride_id is injected by the view when status==SUCCESS
    ride_id = serializers.SerializerMethodField()

    class Meta:
        model = Command
        fields = [
            "request_id",
            "type",
            "status",
            "bike_id",
            "station_id",
            "dock_index",
            "failure_reason",
            "created_at",
            "resolved_at",
            "expires_at",
            "ride_id",
        ]

    def get_ride_id(self, obj):
        # OneToOne reverse accessor — only exists on SUCCESS commands
        try:
            return str(obj.ride.ride_id)
        except Exception:
            return None
