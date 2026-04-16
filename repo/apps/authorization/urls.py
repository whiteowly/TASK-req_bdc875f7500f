from django.urls import path

from . import views

urlpatterns = [
    path("permissions/grants", views.grant_permission),
]
