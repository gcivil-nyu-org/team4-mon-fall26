from django.db import migrations

from teams.catalog_rules import group_legacy_sports, name_key


def forwards(apps, schema_editor):
    Sport = apps.get_model("teams", "Sport")
    Team = apps.get_model("teams", "Team")
    FreeAgentRequest = apps.get_model("teams", "FreeAgentRequest")

    db = schema_editor.connection.alias
    teams = list(Team.objects.using(db).only("id", "sport"))
    requests = list(FreeAgentRequest.objects.using(db).only("id", "sport"))

    # Gather the original text values from both models.
    values = [team.sport for team in teams]
    values += [request.sport for request in requests]

    grouped = group_legacy_sports(values)

    # Reuse existing catalog entries wherever possible.
    sports_by_key = {}

    for sport in Sport.objects.using(db).order_by("pk"):
        key = name_key(sport.name)
        if key:
            sports_by_key.setdefault(key, sport)

    for key, display_name in grouped.items():
        if key not in sports_by_key:
            sport = Sport.objects.using(db).create(name=display_name)
            sports_by_key[key] = sport

    # Preserve the old text and populate the new references.
    for team in teams:
        sport = sports_by_key.get(name_key(team.sport or ""))
        if sport is not None:
            Team.objects.using(db).filter(pk=team.pk).update(sport_ref_id=sport.pk)

    for request in requests:
        sport = sports_by_key.get(name_key(request.sport or ""))
        if sport is not None:
            FreeAgentRequest.objects.using(db).filter(pk=request.pk).update(
                sport_ref_id=sport.pk
            )


def backwards(apps, schema_editor):
    Team = apps.get_model("teams", "Team")
    FreeAgentRequest = apps.get_model("teams", "FreeAgentRequest")

    db = schema_editor.connection.alias
    # Restore text from the catalog before dropping references.
    for team in (
        Team.objects.using(db)
        .select_related("sport_ref")
        .only("id", "sport_ref", "sport_ref__name")
    ):
        if team.sport_ref_id:
            Team.objects.using(db).filter(pk=team.pk).update(sport=team.sport_ref.name)

    for request in (
        FreeAgentRequest.objects.using(db)
        .select_related("sport_ref")
        .only("id", "sport_ref", "sport_ref__name")
    ):
        if request.sport_ref_id:
            FreeAgentRequest.objects.using(db).filter(pk=request.pk).update(
                sport=request.sport_ref.name
            )


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0006_freeagentrequest_sport_ref_team_sport_ref"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
