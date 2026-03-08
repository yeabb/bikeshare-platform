from django.contrib import admin

from apps.users.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["phone", "status", "is_active", "created_at"]
    list_filter = ["status", "is_active"]
    search_fields = ["phone", "email"]
    readonly_fields = ["id", "created_at", "updated_at"]
