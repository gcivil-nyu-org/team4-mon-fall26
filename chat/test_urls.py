"""Test URLconf: the project URLs plus chat.urls (until playnyu/urls.py includes it)."""

from django.urls import include, path

from playnyu.urls import urlpatterns as project_urlpatterns

urlpatterns = project_urlpatterns + [path("chat/", include("chat.urls"))]
