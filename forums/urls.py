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
]
