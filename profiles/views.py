from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse

from .forms import ProfileForm
from .models import PlayerProfile


def _profile_url(user):
    """The profile page, or the edit page until the profile page (T11) exists."""
    try:
        return reverse("profiles:detail", args=[user.pk])
    except NoReverseMatch:
        return reverse("profiles:edit", args=[user.pk])


@login_required
def edit_profile(request, pk):
    # Loaded separately from request.user so a rejected form never touches the signed-in user object.
    user = get_object_or_404(get_user_model(), pk=pk)
    if user.pk != request.user.pk:
        raise PermissionDenied("You can only edit your own profile.")

    profile = PlayerProfile.objects.filter(user=user).first()
    if profile is None:
        return redirect("profiles:create")
    form = ProfileForm(request.POST or None, instance=profile, user=user)
    if request.method == "POST" and form.is_valid():
        form.save()  # one transaction for the user and profile rows
        messages.success(request, "Your profile has been updated.")
        return redirect(_profile_url(user))
    # Invalid submissions fall through: the form is shown again with errors and nothing is saved.
    return render(request, "profiles/edit_profile.html", {"form": form})


@login_required
def create_profile(request):
    if PlayerProfile.objects.filter(user=request.user).exists():
        messages.info(request, "You already have a profile. You can edit it here.")
        return redirect("profiles:edit", pk=request.user.pk)

    # Loaded separately from request.user so a rejected form never touches the signed-in user object.
    user = get_user_model().objects.get(pk=request.user.pk)
    form = ProfileForm(request.POST or None, instance=PlayerProfile(user=user), user=user)
    if request.method == "POST" and form.is_valid():
        form.save()  # one transaction for the user and profile rows
        messages.success(request, "Your profile has been created.")
        return redirect(_profile_url(user))
    return render(
        request,
        "profiles/edit_profile.html",
        {"form": form, "heading": "Create profile", "button": "Create profile", "rejected": "created"},
    )
