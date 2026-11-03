from django.contrib import admin

from .models import Match


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("__str__", "season", "facility", "starts_at", "status")
    list_filter = ("status", "season")
    search_fields = ("home_team__name", "away_team__name", "facility__name")
