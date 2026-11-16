from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("new/", views.new_conversation, name="new"),
    path("<int:pk>/", views.conversation, name="conversation"),
    path("<int:pk>/report/<int:message_pk>/", views.flag_message, name="flag"),
    path("<int:pk>/leave/", views.leave_group, name="leave"),
    path("block/<int:user_pk>/", views.block_user, name="block"),
    path("teams/<int:team_pk>/", views.team_thread_redirect, name="thread"),
    path("moderation/", views.moderation_queue, name="moderation_queue"),
    path(
        "moderation/<int:message_pk>/",
        views.moderate_message,
        name="moderate",
    ),
]
