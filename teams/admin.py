from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .default_seasons import created_seasons_message, ensure_default_seasons
from .models import (
    EventType,
    FreeAgentRequest,
    Roster,
    Season,
    Sport,
    Team,
    season_team_for,
)


class RosterInlineFormSet(BaseInlineFormSet):
    """Roster.clean checks one row against saved rows. This covers what it can't
    see: several new rows at once, and rows for a team that isn't saved yet."""

    def clean(self):
        super().clean()
        team = self.instance
        rows = [
            form
            for form in self.forms
            if form.cleaned_data.get("player") and not self._should_delete_form(form)
        ]
        new_rows = [form for form in rows if form.instance.pk is None]
        if not new_rows:
            return
        if len(rows) > team.max_roster_size:
            raise ValidationError(
                f"The roster is full ({team.max_roster_size} players)."
            )
        for form in new_rows:
            current = season_team_for(form.cleaned_data["player"], team.season)
            if current is not None and current.pk != team.pk:
                raise ValidationError(
                    "That player is already on another team this season."
                )


class RosterInline(admin.TabularInline):
    model = Roster
    formset = RosterInlineFormSet
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "sport", "season", "division", "captain", "created_at")
    inlines = [RosterInline]


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            seasons = ensure_default_seasons(obj)
            if seasons:
                self.message_user(request, created_seasons_message(seasons))


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "sport")
    list_filter = ("sport",)
    search_fields = ("name", "sport__name")


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "state", "start_date", "end_date", "max_roster_size")
    list_filter = ("state",)
    # State changes only along the allowed transitions, on the League Admin seasons page.
    readonly_fields = ("state",)


admin.site.register(Roster)
admin.site.register(FreeAgentRequest)
