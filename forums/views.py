from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.roles import LEAGUE_ADMIN_ROLE, has_role
from audit.models import AuditLog
from teams.models import Sport

from .forms import ReplyForm, TopicForm
from .models import Topic
from .selectors import topics_with_reply_counts

TOPICS_PER_PAGE = 20
GENERAL_FILTER = "general"


def can_moderate(user):
    return bool(getattr(user, "is_superuser", False)) or has_role(
        user, LEAGUE_ADMIN_ROLE
    )


def _require_league_admin(user):
    if not can_moderate(user):
        raise PermissionDenied("Only League Admins can delete forum posts.")


def _log_delete(request, instance):
    """Forum posts are not audit-watched models, so log each admin delete here."""
    AuditLog.objects.create(
        actor=request.user,
        action=AuditLog.Action.DELETED,
        object_type=type(instance).__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
    )


@login_required
def topic_list(request):
    topics = topics_with_reply_counts()
    sports = Sport.objects.order_by("name")

    # The filter is "" (all), "general" (no sport) or a sport id.
    selected = request.GET.get("sport", "")
    selected_label = ""
    if selected == GENERAL_FILTER:
        topics = topics.filter(sport__isnull=True)
        selected_label = "General"
    elif selected.isdigit() and (sport := sports.filter(pk=int(selected)).first()):
        topics = topics.filter(sport=sport)
        selected_label = sport.name
    else:
        selected = ""

    page_obj = Paginator(topics, TOPICS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "forums/topic_list.html",
        {
            "page_obj": page_obj,
            "sports": sports,
            "selected": selected,
            "selected_label": selected_label,
            "general_filter": GENERAL_FILTER,
        },
    )


@login_required
def topic_create(request):
    form = TopicForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        topic = form.save(commit=False)
        topic.author = request.user
        topic.save()
        messages.success(request, "Topic posted.")
        return redirect("forums:detail", pk=topic.pk)
    return render(request, "forums/topic_form.html", {"form": form})


@login_required
def topic_detail(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("author", "sport"), pk=pk)
    form = ReplyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        reply = form.save(commit=False)
        reply.topic = topic
        reply.author = request.user
        reply.save()
        messages.success(request, "Reply posted.")
        return redirect("forums:detail", pk=topic.pk)
    return render(
        request,
        "forums/topic_detail.html",
        {
            "topic": topic,
            "replies": topic.replies.select_related("author"),
            "form": form,
            "can_moderate": can_moderate(request.user),
        },
    )


@login_required
@require_POST
def topic_delete(request, pk):
    _require_league_admin(request.user)
    topic = get_object_or_404(Topic, pk=pk)
    _log_delete(request, topic)
    topic.delete()
    messages.success(request, "Topic deleted.")
    return redirect("forums:list")


@login_required
@require_POST
def reply_delete(request, pk, reply_pk):
    _require_league_admin(request.user)
    topic = get_object_or_404(Topic, pk=pk)
    reply = get_object_or_404(topic.replies, pk=reply_pk)
    _log_delete(request, reply)
    reply.delete()
    messages.success(request, "Reply deleted.")
    return redirect("forums:detail", pk=topic.pk)
