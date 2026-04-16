from django.urls import path

from . import views

urlpatterns = [
    path("datasets", views.datasets),
    path("datasets/<str:dataset_id>", views.dataset_detail),
    path("datasets/<str:dataset_id>/fields", views.dataset_fields),
    path("datasets/<str:dataset_id>/metadata", views.dataset_metadata),
]
