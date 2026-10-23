from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("verify/sent/", views.check_email, name="check_email"),
    path("verify/resend/", views.resend_verification, name="resend"),
    path("verify/<uidb64>/<token>/", views.verify, name="verify"),
]
