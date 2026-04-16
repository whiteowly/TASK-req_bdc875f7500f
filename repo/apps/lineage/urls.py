from django.urls import path

from . import views

urlpatterns = [
    path("lineage/edges", views.edges),
    path("lineage/graph", views.graph),
]
