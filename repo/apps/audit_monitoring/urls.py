from django.urls import path

from . import views

urlpatterns = [
    path("monitoring/metrics", views.metrics),
    path("monitoring/events", views.post_event),
    path("audit/logs", views.audit_logs),
    path("audit/exports", views.audit_export),
]
