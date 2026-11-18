from django.contrib import messages as django_messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from teams.models import Roster, Team

from .forms import MessageForm, NewConversationForm
from .inbox import (
    blockable_users,
    can_post,
    can_view,
    consume_new_conversation,
    get_conversation_for,
    inbox_rows,
    is_blocked_between,
    mark_read,
    open_direct,
    other_member,
    reachable_users,
    retry_after_minutes,
    search_people,
    start_group,
)
from .models import Block, Conversation, ConversationMember, Message
from .moderation import flagged_content, queue_label
from .names import conversation_label

PAGE_SIZE = 50


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
def inbox(request):
    rows = inbox_rows(request.user)
    return render(
        request,
        "chat/inbox.html",
        {
            "rows": rows,
            "active": None,
            "active_label": "",
            "chat_messages": [],
            "older_before": None,
            "form": MessageForm(),
            "can_post": False,
        },
    )


@login_required
def conversation(request, pk):
    chat = get_conversation_for(request.user, pk)
    if request.method == "POST":
        if not can_post(request.user, chat):
            raise PermissionDenied
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.conversation = chat
            message.author = request.user
            message.save()
            mark_read(request.user, chat)
            return redirect(reverse("chat:conversation", args=[chat.pk]) + "#latest")
    else:
        form = MessageForm()
    # Take the time before the query. A message that lands during the query
    # then stays unread.
    opened_at = timezone.now()
    base = chat.messages.select_related("author").order_by("created_at", "pk")
    before_pk = _int_or_none(request.GET.get("before"))
    if before_pk is not None and base.filter(pk=before_pk).exists():
        base = base.filter(pk__lt=before_pk)
    window = list(base.order_by("-created_at", "-pk")[:PAGE_SIZE])
    window.reverse()
    older_before = None
    if len(window) == PAGE_SIZE and base.filter(pk__lt=window[0].pk).exists():
        older_before = window[0].pk
    if request.method != "POST":
        mark_read(request.user, chat, opened_at)
    other_user = other_member(chat, request.user)
    if chat.kind == Conversation.Kind.TEAM:
        season = f" · {chat.team.season}" if chat.team.season_id else ""
        active_meta = f"{chat.team.sport}{season}"
    elif chat.kind == Conversation.Kind.DIRECT:
        active_meta = "Direct message"
    else:
        members = ConversationMember.objects.filter(
            conversation=chat, left_at__isnull=True
        ).count()
        active_meta = "1 person" if members == 1 else f"{members} people"
    return render(
        request,
        "chat/inbox.html",
        {
            "rows": inbox_rows(request.user),
            "active": chat,
            "active_label": conversation_label(chat, request.user),
            "active_meta": active_meta,
            "other_user": other_user,
            "is_blocked": (
                is_blocked_between(request.user, other_user)
                if other_user is not None
                else False
            ),
            "chat_messages": window,
            "older_before": older_before,
            "form": form,
            "can_post": can_post(request.user, chat),
        },
    )


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
@require_POST
def flag_message(request, pk, message_pk):
    chat = get_conversation_for(request.user, pk)
    message = get_object_or_404(chat.messages, pk=message_pk)
    if message.author_id != request.user.pk and not message.is_flagged:
        message.is_flagged = True
        message.save(update_fields=["is_flagged"])
        django_messages.warning(request, "Message reported for League Admin review.")
    return redirect("chat:conversation", pk=chat.pk)


@login_required
def team_thread_redirect(request, team_pk):
    team = _get_team_for_member(team_pk, request.user)
    return redirect("chat:conversation", pk=Conversation.for_team(team).pk)


@login_required
def new_conversation(request):
    form = NewConversationForm(request.user)
    query = (request.GET.get("q") or "").strip()
    results = search_people(request.user, query) if query else []
    chosen, has_bad = _chosen_people(request)
    if request.method == "GET" and not query and len(chosen) == 1 and not has_bad:
        existing = Conversation.objects.filter(
            direct_key=Conversation.direct_key_for(request.user, chosen[0])
        ).first()
        if existing is not None and can_view(request.user, existing):
            return redirect("chat:conversation", pk=existing.pk)
    if request.method == "POST":
        form = NewConversationForm(request.user, request.POST)
        if form.is_valid():
            people = form.cleaned_data["people"]
            if len(people) == 1:
                chat, created = open_direct(request.user, people[0])
                if not created:
                    return redirect("chat:conversation", pk=chat.pk)
                decision = consume_new_conversation(request.user)
                if decision.allowed:
                    return redirect("chat:conversation", pk=chat.pk)
                chat.delete()
                form.add_error(None, _limit_message(decision.retry_after))
            else:
                decision = consume_new_conversation(request.user)
                if decision.allowed:
                    chat = start_group(
                        request.user,
                        people,
                        title=form.cleaned_data.get("title", ""),
                    )
                    return redirect("chat:conversation", pk=chat.pk)
                form.add_error(None, _limit_message(decision.retry_after))
        chosen, has_bad = _chosen_people(request, form)
    _attach_shared_teams(request.user, results)
    _attach_shared_teams(request.user, chosen)
    return render(
        request,
        "chat/new.html",
        {
            "q": query,
            "results": results,
            "chosen": chosen,
            "has_bad": has_bad,
            "form": form,
        },
    )


def _limit_message(retry_after):
    return (
        "You've started a lot of chats. Try again in "
        f"{retry_after_minutes(retry_after)} minutes."
    )


def _chosen_people(request, form=None):
    """The valid people picked so far, plus whether any pick was bad."""
    if request.method == "POST" and form is not None and form.is_valid():
        return list(form.cleaned_data["people"]), False
    data = request.POST if request.method == "POST" else request.GET
    raw_values = data.getlist("to") if hasattr(data, "getlist") else []
    reachable = set(reachable_users(request.user).values_list("pk", flat=True))
    User = get_user_model()
    chosen, seen, has_bad = [], set(), False
    for raw in raw_values:
        pk = _int_or_none(raw)
        if pk is None:
            has_bad = True
            continue
        if pk in seen:
            continue
        seen.add(pk)
        if pk == request.user.pk or pk not in reachable:
            has_bad = True
            continue
        chosen.append(User.objects.get(pk=pk))
    chosen.sort(key=lambda person: (person.first_name or "", person.last_name or ""))
    return chosen, has_bad


def _attach_shared_teams(user, people):
    """Name one team the viewer shares with each person, when there is one."""
    people = list(people)
    if not people:
        return
    viewer_teams = set(
        Roster.objects.filter(player=user).values_list("team_id", flat=True)
    )
    if not viewer_teams:
        for person in people:
            person.shared_team = ""
        return
    shared = {}
    memberships = (
        Roster.objects.filter(
            player__in=[person.pk for person in people], team_id__in=viewer_teams
        )
        .select_related("team")
        .order_by("team__name")
    )
    for membership in memberships:
        shared.setdefault(membership.player_id, membership.team.name)
    for person in people:
        person.shared_team = shared.get(person.pk, "")


@login_required
@require_POST
def block_user(request, user_pk):
    # The same reply for a missing, inactive, placeholder or own pk, so the
    # response doesn't tell whether an account exists.
    target = blockable_users(request.user).filter(pk=user_pk).first()
    if target is None:
        django_messages.info(request, "You can't block or unblock this person.")
        return redirect("chat:inbox")
    action = request.POST.get("action")
    if action == "block":
        Block.objects.get_or_create(blocker=request.user, blocked=target)
        django_messages.success(request, "Blocked.")
    elif action == "unblock":
        Block.objects.filter(blocker=request.user, blocked=target).delete()
        django_messages.success(request, "Unblocked.")
    next_pk = _int_or_none(request.POST.get("next"))
    if next_pk is not None:
        try:
            chat = get_conversation_for(request.user, next_pk)
        except Http404:
            pass
        else:
            return redirect("chat:conversation", pk=chat.pk)
    return redirect("chat:inbox")


@login_required
@require_POST
def leave_group(request, pk):
    chat = get_conversation_for(request.user, pk)
    if chat.kind != Conversation.Kind.GROUP:
        raise Http404
    ConversationMember.objects.filter(
        conversation=chat, user=request.user, left_at__isnull=True
    ).update(left_at=timezone.now())
    django_messages.success(request, "You left the chat.")
    return redirect("chat:inbox")


@login_required
def moderation_queue(request):
    _require_league_admin(request.user)
    return render(request, "chat/moderation_queue.html", flagged_content())


@login_required
@require_POST
def moderate_message(request, message_pk):
    _require_league_admin(request.user)
    # Only reported messages. Admins get no access to unreported chats.
    message = get_object_or_404(
        Message.objects.filter(is_flagged=True).select_related("conversation__team"),
        pk=message_pk,
    )
    label = queue_label(message.conversation)
    action = request.POST.get("action")
    if action == "dismiss":
        message.is_flagged = False
        message.save(update_fields=["is_flagged"])
        django_messages.success(request, "Report dismissed.")
    elif action == "delete":
        message.delete()
        django_messages.success(request, f"Message deleted from {label}.")
    else:
        django_messages.error(request, "Choose dismiss or delete.")
        return redirect("chat:moderation_queue")
    return redirect("chat:moderation_queue")
