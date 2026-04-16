from django.urls import path

from . import views

urlpatterns = [
    path("auth/login", views.login_view),
    path("auth/logout", views.logout_view),
    path("auth/sessions", views.list_sessions_view),
    path("auth/sessions/<str:session_id>/revoke", views.revoke_session_view),
    path("users", views.users_collection),
    path("users/<str:user_id>", views.user_detail),
    path("users/<str:user_id>/roles", views.user_roles),
]
