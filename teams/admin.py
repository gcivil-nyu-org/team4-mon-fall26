from django.contrib import admin

from .models import EventType, FreeAgentRequest, Roster, Season, Sport, Team


class RosterInline(admin.TabularInline):
    model = Roster
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "sport", "season", "division", "captain", "created_at")
    inlines = [RosterInline]


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


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
