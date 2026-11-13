from django.urls import path

from . import views

app_name = "forums"

urlpatterns = [
    path("", views.topic_list, name="list"),
    path("new/", views.topic_create, name="create"),
    path("<int:pk>/", views.topic_detail, name="detail"),
    path("<int:pk>/delete/", views.topic_delete, name="delete_topic"),
    path(
        "<int:pk>/replies/<int:reply_pk>/delete/",
        views.reply_delete,
        name="delete_reply",
    ),
    path("<int:pk>/report/", views.topic_report, name="report_topic"),
    path(
        "<int:pk>/replies/<int:reply_pk>/report/",
        views.reply_report,
        name="report_reply",
    ),
    path("moderation/topics/<int:pk>/", views.topic_moderate, name="moderate_topic"),
    path(
        "moderation/replies/<int:reply_pk>/",
        views.reply_moderate,
        name="moderate_reply",
    ),
]
