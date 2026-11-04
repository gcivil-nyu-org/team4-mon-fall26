from django.db import migrations


def create_scorekeeper_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.using(schema_editor.connection.alias).get_or_create(
        name="Scorekeeper"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_account_roles"),
    ]

    operations = [
        migrations.RunPython(create_scorekeeper_role, migrations.RunPython.noop),
    ]
