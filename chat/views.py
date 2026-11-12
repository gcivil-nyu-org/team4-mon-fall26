from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from teams.models import Team

from .forms import MessageForm
from .models import Message


def _get_team_for_member(team_pk, user):
    """Team thread, or 404 so non-members can't tell the team exists."""
    team = get_object_or_404(Team.objects.select_related("season"), pk=team_pk)
    if not team.roster.filter(player=user).exists():
        raise Http404
    return team


def _require_league_admin(user):
    if not (getattr(user, "is_superuser", False) or has_role(user, LEAGUE_ADMIN_ROLE)):
        raise PermissionDenied("Only League Admins can moderate chat.")


@login_required
def team_thread(request, team_pk):
    team = _get_team_for_member(team_pk, request.user)
    form = MessageForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            message = form.save(commit=False)
            message.team = team
            message.author = request.user
            message.save()
            django_messages.success(request, "Message sent.")
            return redirect("chat:thread", team_pk=team.pk)
    chat_messages = team.chat_messages.select_related("author").order_by(
        "created_at", "pk"
    )
    return render(
        request,
        "chat/thread.html",
        {"team": team, "form": form, "chat_messages": chat_messages},
    )


@login_required
@require_POST
def flag_message(request, team_pk, message_pk):
    team = _get_team_for_member(team_pk, request.user)
    message = get_object_or_404(team.chat_messages, pk=message_pk)
    if not message.is_flagged:
        message.is_flagged = True
        message.save(update_fields=["is_flagged"])
        django_messages.warning(request, "Message reported for League Admin review.")
    return redirect("chat:thread", team_pk=team.pk)


@login_required
def moderation_queue(request):
    _require_league_admin(request.user)
    flagged = Message.objects.filter(is_flagged=True).select_related("team", "author")
    return render(request, "chat/moderation_queue.html", {"flagged": flagged})


@login_required
@require_POST
def moderate_message(request, message_pk):
    _require_league_admin(request.user)
    message = get_object_or_404(Message.objects.select_related("team"), pk=message_pk)
    action = request.POST.get("action")
    if action == "dismiss":
        message.is_flagged = False
        message.save(update_fields=["is_flagged"])
        django_messages.success(request, "Report dismissed.")
    elif action == "delete":
        team_name = message.team.name
        message.delete()
        django_messages.success(request, f"Message deleted from {team_name}.")
    else:
        django_messages.error(request, "Choose dismiss or delete.")
        return redirect("chat:moderation_queue")
    return redirect("chat:moderation_queue")
