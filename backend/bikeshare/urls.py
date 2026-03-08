from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/stations/", include("apps.stations.urls")),
    path("api/v1/commands/", include("apps.commands.urls")),
    path("api/v1/me/", include("apps.rides.urls")),
]
