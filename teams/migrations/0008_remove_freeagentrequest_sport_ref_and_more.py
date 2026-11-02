import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0007_backfill_sports"),
    ]

    operations = [
        # Preserve the old text field temporarily.
        migrations.RenameField(
            model_name="team",
            old_name="sport",
            new_name="sport_legacy",
        ),
        migrations.RenameField(
            model_name="freeagentrequest",
            old_name="sport",
            new_name="sport_legacy",
        ),
        # Promote the populated foreign keys to the final field names.
        migrations.RenameField(
            model_name="team",
            old_name="sport_ref",
            new_name="sport",
        ),
        migrations.RenameField(
            model_name="freeagentrequest",
            old_name="sport_ref",
            new_name="sport",
        ),
        # Make the new Sport relationships mandatory.
        migrations.AlterField(
            model_name="team",
            name="sport",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="teams",
                to="teams.sport",
            ),
        ),
        migrations.AlterField(
            model_name="freeagentrequest",
            name="sport",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="free_agent_requests",
                to="teams.sport",
            ),
        ),
        # Remove the old text columns only after preserving the relationships.
        migrations.RemoveField(
            model_name="team",
            name="sport_legacy",
        ),
        migrations.RemoveField(
            model_name="freeagentrequest",
            name="sport_legacy",
        ),
    ]
