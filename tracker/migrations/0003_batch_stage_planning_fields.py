from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0002_unique_gravity_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="fermentation_started_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Optional exact time fermentation began, such as when yeast "
                    "was pitched."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="planned_conditioning_days",
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    "Optional planned conditioning window in days. Reaching it "
                    "does not change the batch status."
                ),
                null=True,
                validators=[
                    MinValueValidator(1),
                    MaxValueValidator(3650),
                ],
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="target_fermentation_sg",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text=(
                    "Optional target specific gravity used for progress estimates. "
                    "It never changes the batch status automatically."
                ),
                max_digits=5,
                null=True,
                validators=[
                    MinValueValidator(Decimal("0.5000")),
                    MaxValueValidator(Decimal("2.0000")),
                ],
            ),
        ),
    ]
