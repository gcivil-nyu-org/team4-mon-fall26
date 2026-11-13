"""League Admin page that generates a season's round-robin schedule."""

import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse

from facilities.models import Facility
from teams.forms import SeasonFieldsMixin
from teams.models import Division, Season
from teams.season_rules import SeasonAction
from teams.views import _require_league_admin

from .round_robin import create_planned_matches, plan_round_robin

CONFIRM_FIELD = "confirm"
NOT_SCHEDULABLE = "Matches can only be scheduled while a season is open or active."


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kwargs):
        super().__init__(format="%H:%M", **kwargs)


class RoundRobinForm(SeasonFieldsMixin, forms.Form):
    """What a round-robin needs. A valid form holds the plan in `self.plan`."""

    season = forms.ModelChoiceField(
        queryset=Season.objects.none(),
        label="Season",
        empty_label="Choose a season",
        error_messages={"invalid_choice": NOT_SCHEDULABLE},
    )
    division = forms.ModelChoiceField(
        queryset=Division.objects.none(),
        label="Division",
        required=False,
        empty_label="All teams in the season",
        help_text="Choose a division of the season to schedule only its teams.",
    )
    first_date = forms.DateField(label="First match date", widget=DateInput())
    start_time = forms.TimeField(
        label="Start time",
        widget=TimeInput(),
        initial=datetime.time(18, 0),
        help_text="New York time.",
    )
    match_length = forms.IntegerField(
        label="Match length (minutes)", min_value=15, max_value=480, initial=60
    )
    days_between_rounds = forms.IntegerField(
        label="Days between rounds", min_value=1, max_value=60, initial=7
    )
    facilities = forms.ModelMultipleChoiceField(
        queryset=Facility.objects.none(),
        label="Facilities",
        required=False,
        help_text="Leave empty to use any active facility. When a round has more "
        "matches than facilities, the later matches start after the earlier "
        "ones end.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = None
        self.setup_season_fields(Season.objects.allowing(SeasonAction.SCHEDULE_MATCH))
        self.fields["facilities"].queryset = Facility.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if not Facility.objects.filter(is_active=True).exists():
            raise ValidationError("Add an active facility before you schedule matches.")
        season, division = cleaned["season"], cleaned["division"]
        plan = plan_round_robin(
            season,
            division=division,
            first_date=cleaned["first_date"],
            start_time=cleaned["start_time"],
            match_length=datetime.timedelta(minutes=cleaned["match_length"]),
            days_between_rounds=cleaned["days_between_rounds"],
            facilities=list(cleaned["facilities"]),
        )
        if not plan.pair_count:
            scope = f"{division.name} in {season.name}" if division else season.name
            raise ValidationError(
                f"A round-robin needs at least 2 teams that play the same sport. "
                f"{scope} doesn't have them yet."
            )
        self.plan = plan
        return cleaned


@login_required
def round_robin(request):
    """Preview a round-robin schedule, then create it.

    Both steps post the same form. The plan is computed again from the form on
    confirm, and the confirm value must match that plan, so nothing the
    browser sends decides which matches are created.
    """
    _require_league_admin(request.user)
    initial = {}
    if request.GET.get("season", "").isdecimal():
        initial["season"] = request.GET["season"]
    form = RoundRobinForm(request.POST or None, initial=initial)
    plan = None
    if request.method == "POST" and form.is_valid():
        plan = form.plan
        if CONFIRM_FIELD in request.POST and plan.matches:
            if request.POST[CONFIRM_FIELD] != plan.token:
                messages.warning(
                    request,
                    "The schedule changed since the preview. Check it again, "
                    "then create the matches.",
                )
            else:
                try:
                    created = create_planned_matches(plan, created_by=request.user)
                except ValidationError as error:
                    form.add_error(None, error)
                    plan = None
                else:
                    count = len(created)
                    messages.success(
                        request,
                        f"Scheduled {count} match{'' if count == 1 else 'es'} "
                        f"in {plan.season.name}.",
                    )
                    return redirect(
                        f"{reverse('matches:manage')}?season={plan.season.pk}"
                    )
    return render(
        request,
        "matches/round_robin.html",
        {
            "form": form,
            "plan": plan,
            "confirm_field": CONFIRM_FIELD,
            "nav_section": "league_setup",
        },
    )
