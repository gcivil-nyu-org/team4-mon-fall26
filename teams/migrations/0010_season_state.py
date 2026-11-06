from django.db import migrations, models

from teams.season_rules import SeasonState, state_from_legacy_is_active


def is_active_to_state(apps, schema_editor):
    Season = apps.get_model("teams", "Season")
    for season in Season.objects.all():
        season.state = state_from_legacy_is_active(season.is_active)
        season.save(update_fields=["state"])


def state_to_is_active(apps, schema_editor):
    Season = apps.get_model("teams", "Season")
    for season in Season.objects.all():
        season.is_active = season.state in (SeasonState.OPEN, SeasonState.ACTIVE)
        season.save(update_fields=["is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0009_merge_20261102_1821"),
    ]

    operations = [
        migrations.AddField(
            model_name="season",
            name="state",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("open", "Open"),
                    ("active", "Active"),
                    ("closed", "Closed"),
                ],
                default="draft",
                max_length=10,
            ),
        ),
        migrations.RunPython(is_active_to_state, state_to_is_active),
        migrations.RemoveField(model_name="season", name="is_active"),
    ]
