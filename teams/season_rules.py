"""Season lifecycle, dates and division rules for E2. See docs/E2_CONTRACT.md."""

from django.core.exceptions import ValidationError
from django.db import models


class SeasonState(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"


ALLOWED_TRANSITIONS = {
    SeasonState.DRAFT: frozenset({SeasonState.OPEN}),
    SeasonState.OPEN: frozenset({SeasonState.DRAFT, SeasonState.ACTIVE}),
    SeasonState.ACTIVE: frozenset({SeasonState.CLOSED}),
    SeasonState.CLOSED: frozenset(),
}


def can_transition(current, target):
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def _label(state):
    return SeasonState(state).label if state in SeasonState.values else state


def validate_transition(current, target):
    if not can_transition(current, target):
        raise ValidationError(
            f"A season can't move from {_label(current)} to {_label(target)}."
        )


class SeasonAction(models.TextChoices):
    CREATE_TEAM = "create_team", "Create team"
    REQUEST_FREE_AGENT = "request_free_agent", "Request free agent"
    MATCH_FREE_AGENTS = "match_free_agents", "Match free agents"


ALLOWED_ACTIONS = {
    SeasonState.DRAFT: frozenset(),
    SeasonState.OPEN: frozenset(SeasonAction.values),
    SeasonState.ACTIVE: frozenset(
        {SeasonAction.REQUEST_FREE_AGENT, SeasonAction.MATCH_FREE_AGENTS}
    ),
    SeasonState.CLOSED: frozenset(),
}


def season_allows(state, action):
    return action in ALLOWED_ACTIONS.get(state, frozenset())


def validate_season_dates(start_date, end_date):
    if end_date is not None and end_date < start_date:
        raise ValidationError(
            {"end_date": "The end date can't be before the start date."}
        )


def state_from_legacy_is_active(is_active):
    return SeasonState.OPEN if is_active else SeasonState.CLOSED


def division_matches(team_division_id, request_division_id):
    """A request with no division matches any team; otherwise the divisions must match."""
    return request_division_id is None or team_division_id == request_division_id
