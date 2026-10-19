from django.contrib import admin

from .models import Roster, Season, Team


class RosterInline(admin.TabularInline):
    model = Roster
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "sport", "season", "captain", "created_at")
    inlines = [RosterInline]


admin.site.register(Season)
admin.site.register(Roster)
