"""The match sheet: final score, period scores, appearances and player stats.

One page posts all of it. MatchSheet validates the parts and hands the result
to matches.stats.save_match_sheet, the only writer.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils.crypto import salted_hmac

from core.names import display_name
from teams.event_types import scoring_event_type

from .forms import ScoreForm
from .stats import check_one_team, match_event_types, save_match_sheet, team_sheets

MAX_NUMBER = 9999
PERIOD_PREFIX = "period"
OVERTIME_NEEDS_TIE = "Overtime can only be entered when the regular periods end tied."
SCORE_CONFIRMATION_FIELD = "score_confirmation"


def _number_field():
    return forms.IntegerField(required=False, min_value=0, max_value=MAX_NUMBER)


class PeriodForm(forms.Form):
    home_points = _number_field()
    away_points = _number_field()

    def __init__(self, *args, period=None, label="", is_overtime=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.period = period
        self.label = label
        self.is_overtime = is_overtime

    def points(self):
        data = getattr(self, "cleaned_data", {})
        return data.get("home_points"), data.get("away_points")

    @property
    def is_blank(self):
        return self.points() == (None, None)

    @property
    def is_filled(self):
        return None not in self.points()


class BasePeriodFormSet(forms.BaseFormSet):
    """One form per regular period, then OT1 and OT2. No add or delete."""

    def __init__(self, *args, sport, **kwargs):
        self.sport = sport
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        if index is not None:
            period = index + 1
            kwargs.update(
                period=period,
                label=self.sport.period_name(period),
                is_overtime=period > self.sport.period_count,
            )
        return kwargs

    def clean(self):
        if any(form.errors for form in self.forms):
            return
        regular = [form for form in self.forms if not form.is_overtime]
        overtime = [form for form in self.forms if form.is_overtime]
        errors = []
        all_regular = all(form.is_filled for form in regular)
        if not all_regular and not all(form.is_blank for form in regular):
            errors.append("Enter every period, or leave them all blank.")
        if any(not (form.is_blank or form.is_filled) for form in overtime):
            errors.append("Enter both teams' points.")
        for earlier, later in zip(overtime, overtime[1:]):
            if earlier.is_blank and not later.is_blank:
                errors.append(f"Enter {earlier.label} before {later.label}.")
        if not all_regular and any(not form.is_blank for form in overtime):
            errors.append("Enter the regular periods before overtime.")
        if not errors and not self._overtime_follows_ties(regular, overtime):
            errors.append(OVERTIME_NEEDS_TIE)
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _overtime_follows_ties(regular, overtime):
        """Each filled overtime period starts from a tied score."""
        home = sum(form.points()[0] or 0 for form in regular)
        away = sum(form.points()[1] or 0 for form in regular)
        for form in overtime:
            if form.is_blank:
                break
            if home != away:
                return False
            home += form.points()[0]
            away += form.points()[1]
        return True

    def filled(self):
        """[(period, home, away)] for every complete row."""
        return [(form.period, *form.points()) for form in self.forms if form.is_filled]


PeriodFormSet = forms.formset_factory(PeriodForm, formset=BasePeriodFormSet, extra=0)


def stat_name(team_id, player_id, event_type_id):
    return f"stat-{team_id}-{player_id}-{event_type_id}"


def played_name(team_id, player_id):
    return f"played-{team_id}-{player_id}"


class PlayerStatForm(forms.Form):
    """A Played box and one number per event type, for each roster player.

    Fields exist only for current roster players, so a posted field for anyone
    else is ignored. Players who left show as text and keep their stored rows.
    """

    def __init__(self, *args, sheets, event_types, **kwargs):
        super().__init__(*args, **kwargs)
        self.sheets = sheets
        self.event_types = event_types
        for sheet in sheets:
            for row in sheet.rows:
                if not row.on_roster:
                    continue
                name = display_name(row.player)
                played = forms.BooleanField(required=False, initial=row.played)
                played.widget.attrs["aria-label"] = f"{name} played"
                self.fields[played_name(sheet.team.pk, row.player.pk)] = played
                for event_type in event_types:
                    stat = _number_field()
                    stat.initial = row.stats.get(event_type.pk)
                    stat.widget.attrs["aria-label"] = f"{name}, {event_type.name}"
                    key = stat_name(sheet.team.pk, row.player.pk, event_type.pk)
                    self.fields[key] = stat

    @property
    def grid(self):
        """[(sheet, [(row, played field, [stat fields])])]. A leaver's are None."""
        grid = []
        for sheet in self.sheets:
            rows = []
            for row in sheet.rows:
                team, player = sheet.team.pk, row.player.pk
                if row.on_roster:
                    played = self[played_name(team, player)]
                    stats = [
                        self[stat_name(team, player, event_type.pk)]
                        for event_type in self.event_types
                    ]
                else:
                    played, stats = None, [None] * len(self.event_types)
                    # Shown as text on the form.
                    row.stored_values = row.values(self.event_types)
                rows.append((row, played, stats))
            grid.append((sheet, rows))
        return grid

    def players(self):
        return {
            (sheet.team.pk, row.player.pk)
            for sheet in self.sheets
            for row in sheet.rows
            if row.on_roster
        }

    def stats(self):
        values = {}
        for team, player in self.players():
            for event_type in self.event_types:
                value = self.cleaned_data.get(stat_name(team, player, event_type.pk))
                values[(team, player, event_type.pk)] = value or 0
        return values

    def played(self):
        return {
            (team, player)
            for team, player in self.players()
            if self.cleaned_data.get(played_name(team, player))
        }


class MatchSheet:
    """ScoreForm + PeriodFormSet + PlayerStatForm, validated and saved together."""

    def __init__(self, match, data=None):
        self.match = match
        sport = match.home_team.sport
        period_total = (
            sport.period_count + sport.MAX_OVERTIME_PERIODS if sport.period_count else 0
        )
        if data is not None:
            # The period rows are fixed, so the management form is set here and
            # not read from the post.
            data = data.copy()
            for name in ("TOTAL_FORMS", "INITIAL_FORMS"):
                data[f"{PERIOD_PREFIX}-{name}"] = str(period_total)
        stored = {row.period: row for row in match.period_scores.all()}
        initial = [
            (
                {
                    "home_points": stored[period].home_points,
                    "away_points": stored[period].away_points,
                }
                if period in stored
                else {}
            )
            for period in range(1, period_total + 1)
        ]
        self.data = data
        self.score_form = ScoreForm(data, instance=match, required=False)
        self.periods = PeriodFormSet(
            data, initial=initial, prefix=PERIOD_PREFIX, sport=sport
        )
        self.event_types = match_event_types(match)
        self.stats = PlayerStatForm(
            data, sheets=team_sheets(match), event_types=self.event_types
        )
        self.scoring_type = scoring_event_type(sport.pk, self.event_types)
        self._errors = []
        self.score_mismatches = []
        self.score_token = ""

    def is_valid(self):
        self._errors = []
        self.score_mismatches = []
        self.score_token = ""
        if self.periods.is_valid() and self.periods.filled():
            # Periods set the final score, so the posted final fields don't count.
            data = self.data.copy()
            for name in ("home_score", "away_score"):
                data.pop(name, None)
            self.score_form = ScoreForm(data, instance=self.match, required=False)
        parts = [self.score_form, self.periods, self.stats]
        if not all([part.is_valid() for part in parts]):
            return False
        final = self._final()
        if not self.periods.filled() and final is None:
            self._errors.append("Enter both scores, or every period.")
            return False
        try:
            check_one_team(self.match, **self._sheet_rows())
        except ValidationError as error:
            self._errors.extend(error.messages)
            return False
        # A mismatch is a warning, not an error, but it holds the save back
        # until the user confirms it.
        self._find_score_mismatches()
        return not self._mismatches_unconfirmed()

    def _scores(self):
        """(home, away) as it will be saved: the period sums, else the final."""
        periods = self.periods.filled()
        if periods:
            return sum(p[1] for p in periods), sum(p[2] for p in periods)
        return self._final()

    def _find_score_mismatches(self):
        """[(team, players' scoring total, team score)] where they differ.

        A total of 0 means no stats were entered, so it isn't a mismatch.
        Players who left count with their stored rows, as on the match page.
        """
        scoring = self.scoring_type
        if scoring is None:
            return
        posted = self.stats.stats()
        for sheet, score in zip(self.stats.sheets, self._scores()):
            total = sum(
                (
                    posted.get((sheet.team.pk, row.player.pk, scoring.pk), 0)
                    if row.on_roster
                    else row.stats.get(scoring.pk, 0)
                )
                for row in sheet.rows
            )
            if total and total != score:
                self.score_mismatches.append((sheet.team, total, score))
        if self.score_mismatches:
            warned_about = (
                self.match.pk,
                [
                    (team.pk, total, score)
                    for team, total, score in self.score_mismatches
                ],
            )
            self.score_token = salted_hmac(
                "matches.score_mismatch", repr(warned_about)
            ).hexdigest()

    def _mismatches_unconfirmed(self):
        submitted = self.data.get(SCORE_CONFIRMATION_FIELD)
        return bool(self.score_mismatches) and submitted != self.score_token

    def non_field_errors(self):
        return list(self.score_form.non_field_errors()) + self.sheet_errors()

    def sheet_errors(self):
        """Errors that belong to no single input. The score card shows its own."""
        return list(self.periods.non_form_errors()) + self._errors

    def _final(self):
        home = self.score_form.cleaned_data.get("home_score")
        away = self.score_form.cleaned_data.get("away_score")
        if home is None or away is None:
            return None
        return home, away

    def _sheet_rows(self):
        return {
            "stats": self.stats.stats(),
            "played": self.stats.played(),
            "players": self.stats.players(),
        }

    def save(self):
        """Save, and return False with the error kept when the writer refuses.

        The writer checks again under the match lock, so a save made by someone
        else since is_valid() becomes a form error, not a server error.
        """
        try:
            save_match_sheet(
                self.match,
                periods=self.periods.filled(),
                final=self._final(),
                **self._sheet_rows(),
            )
        except ValidationError as error:
            self._errors.extend(error.messages)
            return False
        return True
