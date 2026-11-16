"""Set the periods of known sports by name. Other sports keep the default (4, "Q")."""

from django.db import migrations

DEFAULT = (4, "Q")

# Keys are lowercase sport names.
PERIODS = {
    "basketball": (4, "Q"),
    "soccer": (2, "Half"),
    "futsal": (2, "Half"),
    "volleyball": (5, "Set"),
    "flag football": (4, "Q"),
    "ultimate": (2, "Half"),
    "ultimate frisbee": (2, "Half"),
}


def _known_sports(apps):
    Sport = apps.get_model("teams", "Sport")
    for sport in Sport.objects.all():
        periods = PERIODS.get(sport.name.strip().lower())
        if periods:
            yield sport, periods


def set_period_defaults(apps, schema_editor):
    for sport, (count, label) in _known_sports(apps):
        sport.period_count = count
        sport.period_label = label
        sport.save(update_fields=["period_count", "period_label"])


def clear_period_defaults(apps, schema_editor):
    for sport, _ in _known_sports(apps):
        sport.period_count, sport.period_label = DEFAULT
        sport.save(update_fields=["period_count", "period_label"])


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0013_sport_periods"),
    ]

    operations = [
        migrations.RunPython(set_period_defaults, clear_period_defaults),
    ]
