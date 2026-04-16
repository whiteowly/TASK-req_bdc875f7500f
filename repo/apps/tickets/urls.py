from django.urls import path

from . import views

urlpatterns = [
    path("tickets", views.tickets),
    path("tickets/<str:ticket_id>/transition", views.transition),
    path("tickets/<str:ticket_id>/assign", views.assign),
    path("tickets/<str:ticket_id>/remediation-actions", views.remediation_action),
    path("tickets/<str:ticket_id>/backfills", views.backfills),
    path("backfills/<str:backfill_id>", views.backfill_detail),
]
