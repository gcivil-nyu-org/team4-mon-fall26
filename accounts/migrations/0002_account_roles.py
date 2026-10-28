from django.conf import settings
from django.db import migrations


def create_roles_and_assign_verified_users(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    using = schema_editor.connection.alias

    casual_players, _ = Group.objects.using(using).get_or_create(name="Casual Player")
    Group.objects.using(using).get_or_create(name="League Admin")

    membership = User.groups.through
    membership.objects.using(using).bulk_create(
        [
            membership(user_id=user_id, group_id=casual_players.pk)
            for user_id in User.objects.using(using)
            .filter(is_active=True)
            .values_list("pk", flat=True)
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(
            create_roles_and_assign_verified_users,
            migrations.RunPython.noop,
        ),
    ]
