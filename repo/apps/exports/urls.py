from django.urls import path

from . import views

urlpatterns = [
    path("reports/runs/<str:run_id>/exports", views.create_export),
    path("exports/<str:export_job_id>", views.export_detail),
    path("exports/<str:export_job_id>/files", views.export_files),
    path("exports/<str:export_job_id>/files/<int:part_number>/download", views.download_file),
]
