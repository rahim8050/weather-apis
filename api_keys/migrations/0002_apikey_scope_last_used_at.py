from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api_keys", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="scope",
            field=models.CharField(
                choices=[
                    ("read", "Read"),
                    ("write", "Write"),
                    ("admin", "Admin"),
                ],
                default="read",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="apikey",
            name="last_used_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
