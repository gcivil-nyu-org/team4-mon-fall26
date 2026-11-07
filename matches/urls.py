from django.urls import path

from . import views

app_name = "matches"

urlpatterns = [
    path("schedule/", views.schedule_seasons, name="schedule_seasons"),
    path("schedule/<int:pk>/", views.season_schedule, name="season_schedule"),
    path("manage/", views.manage_matches, name="manage"),
    path("manage/new/", views.match_form, name="create"),
    path("manage/<int:pk>/edit/", views.match_form, name="edit"),
    path("manage/<int:pk>/cancel/", views.cancel_match, name="cancel"),
]
