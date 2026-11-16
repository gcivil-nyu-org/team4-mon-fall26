"""Mark one Points or Goals event type per sport as the scoring stat (#254).

A sport that already has a scoring stat keeps it. A sport with none of these
names keeps no scoring stat. The reverse clears every mark.
"""

from django.db import migrations

# Lowercase names, in order of preference. Copied here so later changes to the
# app code don't change this migration.
SCORING_NAMES = ("points", "point", "pts", "goal", "goals")


def _key(name):
    return " ".join(name.split()).casefold()


def mark_scoring_types(apps, schema_editor):
    EventType = apps.get_model("teams", "EventType")
    by_sport = {}
    for event_type in EventType.objects.order_by("pk"):
        by_sport.setdefault(event_type.sport_id, []).append(event_type)
    for types in by_sport.values():
        if any(event_type.is_scoring for event_type in types):
            continue
        known = [t for t in types if _key(t.name) in SCORING_NAMES]
        if not known:
            continue
        chosen = min(known, key=lambda t: SCORING_NAMES.index(_key(t.name)))
        EventType.objects.filter(pk=chosen.pk).update(is_scoring=True)


def clear_scoring_types(apps, schema_editor):
    EventType = apps.get_model("teams", "EventType")
    EventType.objects.filter(is_scoring=True).update(is_scoring=False)


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0015_eventtype_is_scoring"),
    ]

    operations = [
        migrations.RunPython(mark_scoring_types, clear_scoring_types),
    ]
