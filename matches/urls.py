from django.urls import path

from . import comment_views, round_robin_views, views

app_name = "matches"

urlpatterns = [
    path("<int:pk>/", views.match_detail, name="detail"),
    path(
        "<int:pk>/comments/<int:comment_pk>/report/",
        comment_views.comment_report,
        name="report_comment",
    ),
    path(
        "<int:pk>/comments/<int:comment_pk>/delete/",
        comment_views.comment_delete,
        name="delete_comment",
    ),
    path(
        "moderation/comments/<int:comment_pk>/",
        comment_views.comment_moderate,
        name="moderate_comment",
    ),
    path("mine/", views.my_matches, name="mine"),
    path("schedule/", views.schedule, name="schedule"),
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
