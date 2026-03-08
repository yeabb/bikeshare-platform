from django.contrib import admin

from apps.bikes.models import Bike


@admin.register(Bike)
class BikeAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "current_station", "current_dock", "created_at"]
    list_filter = ["status"]
    search_fields = ["id"]
    readonly_fields = ["created_at", "updated_at"]
