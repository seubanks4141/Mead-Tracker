# Generated for the initial Mead Tracker schema.

import uuid
from decimal import Decimal

import django.core.serializers.json
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import tracker.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Batch",
            fields=[
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                (
                    "batch_number",
                    models.CharField(
                        blank=True,
                        help_text="Optional cellar or production identifier.",
                        max_length=50,
                    ),
                ),
                ("style", models.CharField(blank=True, max_length=120)),
                (
                    "start_date",
                    models.DateField(default=django.utils.timezone.localdate),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("planning", "Planning"),
                            ("fermenting", "Fermenting"),
                            ("conditioning", "Conditioning"),
                            ("aging", "Aging"),
                            ("bottled", "Bottled"),
                            ("complete", "Complete"),
                            ("archived", "Archived"),
                        ],
                        default="fermenting",
                        max_length=20,
                    ),
                ),
                (
                    "volume",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=12,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.001")
                            )
                        ],
                    ),
                ),
                (
                    "volume_unit",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("gal", "Gallons (US)"),
                            ("qt", "Quarts (US)"),
                            ("fl_oz", "Fluid ounces (US)"),
                            ("L", "Liters (L)"),
                            ("mL", "Milliliters (mL)"),
                        ],
                        max_length=8,
                    ),
                ),
                ("vessel", models.CharField(blank=True, max_length=160)),
                ("description", models.TextField(blank=True)),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, editable=False),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mead_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-start_date", "-created_at"),
                "indexes": [
                    models.Index(
                        fields=["owner", "status", "deleted_at"],
                        name="tracker_batch_owner_status",
                    ),
                    models.Index(
                        fields=["start_date"],
                        name="tracker_batch_started",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(
                            ("deleted_at__isnull", True),
                            models.Q(("batch_number", ""), _negated=True),
                        ),
                        fields=("owner", "batch_number"),
                        name="uniq_active_owner_batch_no",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Addition",
            fields=[
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("honey", "Honey"),
                            ("water", "Water"),
                            ("fruit", "Fruit"),
                            ("spice", "Spice or herb"),
                            ("yeast", "Yeast"),
                            ("nutrient", "Nutrient"),
                            ("acid", "Acid"),
                            ("tannin", "Tannin"),
                            ("fining", "Fining agent"),
                            ("stabilizer", "Stabilizer"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text=(
                            "For example: wildflower honey, orange peel, or D47 yeast."
                        ),
                        max_length=160,
                    ),
                ),
                (
                    "quantity",
                    models.DecimalField(
                        decimal_places=4,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.0001")
                            )
                        ],
                    ),
                ),
                (
                    "unit",
                    models.CharField(
                        choices=[
                            ("lb", "Pounds (lb)"),
                            ("oz", "Ounces (oz)"),
                            ("kg", "Kilograms (kg)"),
                            ("g", "Grams (g)"),
                            ("gal", "Gallons (US)"),
                            ("qt", "Quarts (US)"),
                            ("fl_oz", "Fluid ounces (US)"),
                            ("L", "Liters (L)"),
                            ("mL", "Milliliters (mL)"),
                            ("cup", "Cups"),
                            ("tbsp", "Tablespoons"),
                            ("tsp", "Teaspoons"),
                            ("count", "Count"),
                            ("other", "Other"),
                        ],
                        max_length=12,
                    ),
                ),
                (
                    "custom_unit",
                    models.CharField(
                        blank=True,
                        help_text="Required only when the unit is Other.",
                        max_length=40,
                    ),
                ),
                (
                    "added_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "phase",
                    models.CharField(
                        choices=[
                            ("must", "Must preparation"),
                            ("primary", "Primary fermentation"),
                            ("secondary", "Secondary fermentation"),
                            ("conditioning", "Conditioning or aging"),
                            ("bottling", "Bottling"),
                            ("other", "Other"),
                        ],
                        default="primary",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "recorded_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="additions",
                        to="tracker.batch",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_additions_recorded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("added_at", "recorded_at"),
                "indexes": [
                    models.Index(
                        fields=["batch", "added_at", "deleted_at"],
                        name="tracker_add_batch_time",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="GravityReading",
            fields=[
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "specific_gravity",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="Enter specific gravity, such as 1.082.",
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.5000")
                            ),
                            django.core.validators.MaxValueValidator(
                                Decimal("2.0000")
                            ),
                        ],
                    ),
                ),
                (
                    "reading_type",
                    models.CharField(
                        choices=[
                            ("original", "Original gravity (OG)"),
                            ("routine", "Routine reading"),
                            ("final", "Final gravity (FG)"),
                        ],
                        default="routine",
                        max_length=12,
                    ),
                ),
                (
                    "measured_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "sample_temperature",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=6,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("-100.00")
                            ),
                            django.core.validators.MaxValueValidator(
                                Decimal("300.00")
                            ),
                        ],
                    ),
                ),
                (
                    "temperature_unit",
                    models.CharField(
                        choices=[("F", "°F"), ("C", "°C")],
                        default="F",
                        max_length=1,
                    ),
                ),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("hydrometer", "Hydrometer"),
                            ("refractometer", "Refractometer"),
                            ("digital", "Digital densitometer"),
                            ("other", "Other"),
                        ],
                        default="hydrometer",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "recorded_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gravity_readings",
                        to="tracker.batch",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_gravity_readings_recorded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("measured_at", "recorded_at"),
                "indexes": [
                    models.Index(
                        fields=["batch", "measured_at", "deleted_at"],
                        name="tracker_grav_batch_time",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Observation",
            fields=[
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "observed_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("general", "General"),
                            ("aroma", "Aroma"),
                            ("flavor", "Flavor"),
                            ("appearance", "Appearance"),
                            ("fermentation", "Fermentation activity"),
                            ("transfer", "Transfer or racking"),
                            ("issue", "Potential issue"),
                            ("other", "Other"),
                        ],
                        default="general",
                        max_length=20,
                    ),
                ),
                ("text", models.TextField()),
                (
                    "recorded_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="observations",
                        to="tracker.batch",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_observations_recorded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("observed_at", "recorded_at"),
                "indexes": [
                    models.Index(
                        fields=["batch", "observed_at", "deleted_at"],
                        name="tracker_obs_batch_time",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="BatchStatusHistory",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("planning", "Planning"),
                            ("fermenting", "Fermenting"),
                            ("conditioning", "Conditioning"),
                            ("aging", "Aging"),
                            ("bottled", "Bottled"),
                            ("complete", "Complete"),
                            ("archived", "Archived"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "changed_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "recorded_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_history",
                        to="tracker.batch",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "batch status history",
                "ordering": ("changed_at", "recorded_at"),
                "indexes": [
                    models.Index(
                        fields=["batch", "changed_at"],
                        name="tracker_status_batch_time",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="QRLink",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "token",
                    models.CharField(
                        default=tracker.models.generate_qr_token,
                        editable=False,
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        help_text="Optional description, such as 'first bottle run'.",
                        max_length=80,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "revoked_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "last_scanned_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "scan_count",
                    models.PositiveIntegerField(default=0, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="qr_links",
                        to="tracker.batch",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_qr_links_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("is_active", True)),
                        fields=("batch",),
                        name="uniq_active_qr_per_batch",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("create", "Created"),
                            ("update", "Updated"),
                            ("delete", "Soft deleted"),
                            ("restore", "Restored"),
                            ("status", "Status changed"),
                            ("qr_rotate", "QR link rotated"),
                        ],
                        max_length=16,
                    ),
                ),
                ("model_name", models.CharField(max_length=80)),
                ("object_id", models.UUIDField(blank=True, null=True)),
                ("object_repr", models.CharField(blank=True, max_length=255)),
                (
                    "changes",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        encoder=django.core.serializers.json.DjangoJSONEncoder,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_audit_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to="tracker.batch",
                    ),
                ),
            ],
            options={
                "ordering": ("-recorded_at",),
                "indexes": [
                    models.Index(
                        fields=["batch", "recorded_at"],
                        name="tracker_audit_batch_time",
                    ),
                    models.Index(
                        fields=["model_name", "object_id"],
                        name="tracker_audit_object",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="LabelPrintLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("label_preset", models.CharField(blank=True, max_length=40)),
                (
                    "width",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=7,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.001")
                            )
                        ],
                    ),
                ),
                (
                    "height",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=7,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.001")
                            )
                        ],
                    ),
                ),
                (
                    "dimension_unit",
                    models.CharField(
                        choices=[("in", "Inches"), ("mm", "Millimeters")],
                        default="in",
                        max_length=2,
                    ),
                ),
                (
                    "output_mode",
                    models.CharField(
                        choices=[
                            ("single", "Single label"),
                            ("letter", "US Letter sheet"),
                        ],
                        default="single",
                        max_length=12,
                    ),
                ),
                (
                    "copies",
                    models.PositiveIntegerField(
                        default=1,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(1000)
                        ],
                    ),
                ),
                (
                    "printed_at",
                    models.DateTimeField(auto_now_add=True, editable=False),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="label_prints",
                        to="tracker.batch",
                    ),
                ),
                (
                    "printed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mead_labels_printed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "qr_link",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="label_prints",
                        to="tracker.qrlink",
                    ),
                ),
            ],
            options={
                "ordering": ("-printed_at",),
                "indexes": [
                    models.Index(
                        fields=["batch", "printed_at"],
                        name="tracker_label_batch_time",
                    )
                ],
            },
        ),
    ]
