from django.urls import path

from . import views

app_name = "facilities"

urlpatterns = [
    path("", views.facility_map, name="map"),
    path("<int:pk>/", views.facility_detail, name="detail"),
    path("manage/", views.manage_facilities, name="manage"),
    path("manage/new/", views.facility_form, name="create"),
    path("manage/<int:pk>/edit/", views.facility_form, name="edit"),
]
