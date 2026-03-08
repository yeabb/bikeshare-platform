from django.contrib import admin

from apps.commands.models import Command


@admin.register(Command)
class CommandAdmin(admin.ModelAdmin):
    list_display = [
        "request_id", "type", "status", "user", "station", "bike", "created_at", "resolved_at"
    ]
    list_filter = ["status", "type"]
    search_fields = ["request_id", "user__phone", "bike__id", "station__id"]
    readonly_fields = ["request_id", "created_at", "updated_at"]
