"""
URL configuration for playnyu project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from accounts.views import NYULoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Login and logout keep the names "login" and "logout" that the rest of the project uses.
    path("accounts/login/", NYULoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("accounts/", include("accounts.urls")),
    path("teams/", include("teams.urls")),
    path("profiles/", include("profiles.urls")),
    path("", include("core.urls")),
]
