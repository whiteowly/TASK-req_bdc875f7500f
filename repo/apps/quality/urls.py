from django.urls import path

from . import views

urlpatterns = [
    path("quality/rules", views.rules),
    path("quality/rules/<str:rule_id>", views.rule_detail),
    path("quality/inspections/trigger", views.trigger_inspection),
    path("quality/inspections", views.list_inspections),
    path("quality/inspections/<str:inspection_id>", views.inspection_detail),
    path("quality/schedules", views.schedules),
]
