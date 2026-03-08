from django.contrib import admin

from apps.stations.models import Dock, Station


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "status", "total_docks", "created_at"]
    list_filter = ["status"]
    search_fields = ["id", "name"]


@admin.register(Dock)
class DockAdmin(admin.ModelAdmin):
    list_display = ["display_id", "station", "dock_index", "state", "current_bike", "fault_code"]
    list_filter = ["state", "station"]
    search_fields = ["station__id"]
    readonly_fields = ["created_at", "updated_at"]
