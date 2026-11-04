from django.urls import path

from . import views

app_name = "facilities"

urlpatterns = [
    path("", views.facility_map, name="map"),
    path("<int:pk>/", views.facility_detail, name="detail"),
]
