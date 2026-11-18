"""Report and remove match comments. Posting lives in views.match_detail.

The report and moderation rules match the forum's, so these views reuse its
helpers: a report flags the comment, and a League Admin dismisses the report
or deletes the comment (with an audit row) from the moderation queue.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from forums.views import _delete_post, _moderate, _report, _require_league_admin
from .models import MatchComment
from .schedule import seasons_visible_to


def _comment(user, pk, comment_pk):
    """The comment, 404 if its match is in a season the user can't see."""
    return get_object_or_404(
        MatchComment.objects.filter(
            match__season__in=seasons_visible_to(user)
        ).select_related("match"),
        match_id=pk,
        pk=comment_pk,
    )


def _comments_url(match_pk):
    return reverse("matches:detail", args=[match_pk]) + "#comments"


@login_required
@require_POST
def comment_report(request, pk, comment_pk):
    comment = _comment(request.user, pk, comment_pk)
    _report(request, comment, "Comment")
    return redirect(_comments_url(pk))


@login_required
@require_POST
def comment_delete(request, pk, comment_pk):
    _require_league_admin(request.user)
    comment = _comment(request.user, pk, comment_pk)
    _delete_post(request, comment)
    messages.success(request, "Comment deleted.")
    return redirect(_comments_url(pk))


@login_required
@require_POST
def comment_moderate(request, comment_pk):
    _require_league_admin(request.user)
    return _moderate(request, get_object_or_404(MatchComment, pk=comment_pk), "Comment")
