from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RateLimitBucket",
            fields=[
                (
                    "bucket_key",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("count", models.PositiveIntegerField(default=0)),
                ("window_started_at", models.DateTimeField(db_index=True)),
                ("last_seen_at", models.DateTimeField(db_index=True)),
            ],
        ),
    ]
