from django.contrib import admin

from apps.rides.models import Ride


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = [
        "ride_id", "user", "bike", "status", "start_station", "end_station",
        "started_at", "ended_at"
    ]
    list_filter = ["status"]
    search_fields = ["ride_id", "user__phone", "bike__id"]
    readonly_fields = ["ride_id", "created_at", "updated_at"]
