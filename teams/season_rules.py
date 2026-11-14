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
    ADD_PLAYER = "add_player", "Add player"
    REMOVE_PLAYER = "remove_player", "Remove player"
    LEAVE_TEAM = "leave_team", "Leave team"
    SCHEDULE_MATCH = "schedule_match", "Schedule match"


ALLOWED_ACTIONS = {
    SeasonState.DRAFT: frozenset(),
    SeasonState.OPEN: frozenset(SeasonAction.values),
    # Players can still be added once play starts, but nobody leaves or is
    # removed, so no one can switch teams mid-season.
    SeasonState.ACTIVE: frozenset(
        {
            SeasonAction.REQUEST_FREE_AGENT,
            SeasonAction.MATCH_FREE_AGENTS,
            SeasonAction.ADD_PLAYER,
            SeasonAction.SCHEDULE_MATCH,
        }
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


def validate_registration_date(registration_closes_on, end_date):
    if (
        registration_closes_on is not None
        and end_date is not None
        and registration_closes_on > end_date
    ):
        raise ValidationError(
            {"registration_closes_on": "Registration can't close after the end date."}
        )


def automatic_states(state, auto_state, registration_closes_on, end_date, today):
    """The states a season moves through on `today`, in order. Empty if none.

    Open becomes active on the day after registration closes, not on the start
    date: default semester seasons are created open with a start date that is
    already past. Active becomes closed on the day after the end date. Draft
    and closed seasons never change, and a missing date never triggers a change.
    """
    steps = []
    if not auto_state:
        return steps
    if (
        state == SeasonState.OPEN
        and registration_closes_on is not None
        and today > registration_closes_on
    ):
        state = SeasonState.ACTIVE
        steps.append(state)
    if state == SeasonState.ACTIVE and end_date is not None and today > end_date:
        steps.append(SeasonState.CLOSED)
    return steps


def state_from_legacy_is_active(is_active):
    return SeasonState.OPEN if is_active else SeasonState.CLOSED


def division_matches(team_division_id, request_division_id):
    """A request with no division matches any team; otherwise the divisions must match."""
    return request_division_id is None or team_division_id == request_division_id
