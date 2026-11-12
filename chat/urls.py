from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("teams/<int:team_pk>/", views.team_thread, name="thread"),
    path(
        "teams/<int:team_pk>/report/<int:message_pk>/",
        views.flag_message,
        name="flag",
    ),
    path("moderation/", views.moderation_queue, name="moderation_queue"),
    path(
        "moderation/<int:message_pk>/",
        views.moderate_message,
        name="moderate",
    ),
]
