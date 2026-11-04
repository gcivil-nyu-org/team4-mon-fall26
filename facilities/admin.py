from django.contrib import admin

from .models import Facility


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "borough", "source", "is_active")
    list_filter = ("source", "borough", "is_active", "sports")
    search_fields = ("name", "address", "external_id")
    filter_horizontal = ("sports",)
