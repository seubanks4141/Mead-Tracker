from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="gravityreading",
            constraint=models.UniqueConstraint(
                fields=("batch", "reading_type"),
                condition=models.Q(
                    deleted_at__isnull=True,
                    reading_type__in=("original", "final"),
                ),
                name="uniq_active_gravity_role",
            ),
        ),
    ]
