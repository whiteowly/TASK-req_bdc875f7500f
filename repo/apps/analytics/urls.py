from django.urls import path

from . import views

urlpatterns = [
    path("analytics/datasets/<str:dataset_id>/query", views.query_dataset),
    path("reports/definitions", views.definitions),
    path("reports/definitions/<str:definition_id>", views.definition_detail),
    path("reports/runs", views.run_report),
    path("reports/runs/<str:run_id>", views.run_detail),
    path("reports/schedules", views.schedules),
    path("reports/schedules/<str:schedule_id>", views.schedule_detail),
]
