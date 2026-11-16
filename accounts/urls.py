from django.urls import path

from . import role_views, views

app_name = "accounts"

urlpatterns = [
    path("roles/", role_views.role_list, name="roles"),
    path("roles/<int:user_pk>/", role_views.change_role, name="change_role"),
    path("signup/", views.signup, name="signup"),
    path("verify/sent/", views.check_email, name="check_email"),
    path("verify/resend/", views.resend_verification, name="resend"),
    path("verify/<uidb64>/<token>/", views.verify, name="verify"),
]
