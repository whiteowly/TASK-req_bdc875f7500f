from django.urls import path

from . import views

urlpatterns = [
    path("content/entries", views.entries),
    path("content/entries/<str:entry_id>", views.entry_detail),
    path("content/entries/<str:entry_id>/versions", views.versions),
    path("content/entries/<str:entry_id>/publish", views.publish),
    path("content/entries/<str:entry_id>/rollback", views.rollback),
    path("content/entries/<str:entry_id>/diff", views.diff),
]
