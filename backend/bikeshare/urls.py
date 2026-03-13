from django.contrib import admin
from django.urls import include, path

from apps.iot.views import internal_station_event

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/stations/", include("apps.stations.urls")),
    path("api/v1/commands/", include("apps.commands.urls")),
    path("api/v1/me/", include("apps.rides.urls")),
    # Internal — called by Lambda only, protected by shared secret
    path("internal/station-event/", internal_station_event),
]
