"""The matches a scorekeeper is assigned to, grouped by what they still need."""

from .models import Match


def assigned_matches(user):
    """The user's assigned matches, with everything a match row shows."""
    return Match.objects.filter(scorekeeper=user).select_related(
        "season", "facility", "home_team__sport", "away_team__sport"
    )


def group_assigned_matches(user):
    """Sort the user's assigned matches into the My matches sections.

    needs_score: started, no result, and still open to a score. Oldest first.
    upcoming: not started yet. Soonest first. Cancelled ones stay, labelled.
    scored: has a result. Newest first.
    unscored: past matches that can't take a score now (cancelled, or the
        season closed). Newest first.
    """
    groups = {"needs_score": [], "upcoming": [], "scored": [], "unscored": []}
    for match in assigned_matches(user):
        if match.has_result:
            groups["scored"].append(match)
        elif not match.has_started:
            groups["upcoming"].append(match)
        elif match.can_submit_score:
            groups["needs_score"].append(match)
        else:
            groups["unscored"].append(match)
    groups["scored"].reverse()
    groups["unscored"].reverse()
    return groups
