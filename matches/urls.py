from django.urls import path

from . import round_robin_views, views

app_name = "matches"

urlpatterns = [
    path("mine/", views.my_matches, name="mine"),
    path("schedule/", views.schedule_seasons, name="schedule_seasons"),
    path("schedule/<int:pk>/", views.season_schedule, name="season_schedule"),
    path("manage/", views.manage_matches, name="manage"),
    path("manage/new/", views.match_form, name="create"),
    path("manage/round-robin/", round_robin_views.round_robin, name="round_robin"),
    path("manage/<int:pk>/edit/", views.match_form, name="edit"),
    path("manage/<int:pk>/cancel/", views.cancel_match, name="cancel"),
    path("manage/<int:pk>/score/", views.record_score, name="score"),
    path("mine/<int:pk>/score/", views.submit_score, name="submit_score"),
    path("standings/", views.standings_seasons, name="standings"),
    path("standings/<int:pk>/", views.season_standings, name="season_standings"),
]
