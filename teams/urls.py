from django.urls import path

from . import views

app_name = "teams"

urlpatterns = [
    path("", views.team_list, name="list"),
    path("new/", views.create_team, name="create"),
    path("<int:pk>/", views.team_detail, name="detail"),
    path("<int:pk>/add-player/", views.add_player, name="add_player"),
    path(
        "<int:pk>/remove/<int:entry_pk>/",
        views.remove_player,
        name="remove_player",
    ),
    path("<int:pk>/leave/", views.leave_team, name="leave"),
    path("free-agents/", views.free_agent_pool, name="free_agent_pool"),
    path(
        "free-agents/cancel/<int:pk>/",
        views.cancel_free_agent_request,
        name="cancel_free_agent_request",
    ),
    path("free-agents/manage/", views.manage_free_agents, name="manage_free_agents"),
    path(
        "free-agents/manage/<int:season_pk>/",
        views.manage_season_free_agents,
        name="manage_season_free_agents",
    ),
    path(
        "free-agents/manage/<int:season_pk>/match/",
        views.match_free_agents,
        name="match_free_agents",
    ),
]
