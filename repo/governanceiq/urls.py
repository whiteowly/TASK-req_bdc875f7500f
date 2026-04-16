"""Top-level URL configuration."""
from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.identity.urls")),
    path("api/v1/", include("apps.authorization.urls")),
    path("api/v1/", include("apps.catalog.urls")),
    path("api/v1/", include("apps.lineage.urls")),
    path("api/v1/", include("apps.analytics.urls")),
    path("api/v1/", include("apps.quality.urls")),
    path("api/v1/", include("apps.tickets.urls")),
    path("api/v1/", include("apps.content.urls")),
    path("api/v1/", include("apps.exports.urls")),
    path("api/v1/", include("apps.audit_monitoring.urls")),
]
