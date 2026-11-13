from django.contrib import admin

from .models import Reply, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("title", "sport", "author", "last_activity_at", "is_flagged")
    list_filter = ("is_flagged", "sport")
    search_fields = ("title", "body", "author__username", "author__email")


@admin.register(Reply)
class ReplyAdmin(admin.ModelAdmin):
    list_display = ("topic", "author", "created_at", "is_flagged")
    list_filter = ("is_flagged",)
    search_fields = ("body", "topic__title", "author__username", "author__email")
