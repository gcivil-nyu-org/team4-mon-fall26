from django import template

register = template.Library()

UPCOMING_LIMIT = 5
RESULTS_LIMIT = 3


@register.inclusion_tag("matches/dashboard/_upcoming.html")
def upcoming_matches_panel(upcoming, past):
    """The dashboard panel: the player's next matches, then recent results.

    Takes the two lists of matches.schedule.player_schedule(). Cancelled
    matches stay among the upcoming ones; a result needs both scores.
    """
    return {
        "upcoming": upcoming[:UPCOMING_LIMIT],
        "results": [match for match in past if match.has_result][:RESULTS_LIMIT],
    }
