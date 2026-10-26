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
]
