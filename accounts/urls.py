from django.urls import path

from . import views

app_name = "accounts"

# login and logout live in playnyu/urls.py under the names "login" and "logout",
# which the rest of the project already uses.
urlpatterns = [
    path("register/", views.register, name="register"),
    path("check-email/", views.check_email, name="check_email"),
    path("verify/<uidb64>/<token>/", views.verify, name="verify"),
    path("resend/", views.resend, name="resend"),
]
