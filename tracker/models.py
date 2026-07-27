"""Database models for the Mead Tracker domain.

The editable timestamps (``added_at``, ``measured_at``, ``observed_at`` and
``changed_at``) describe when something happened in the mead-making process.
The corresponding ``recorded_at`` fields are set by the server and are never
editable.  Keeping the two concepts separate makes back-dated phone entries
possible without losing an audit-friendly record of when data was entered.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q
from django.utils import timezone


MAX_OBSERVATION_PHOTO_BYTES = 10 * 1024 * 1024
logger = logging.getLogger(__name__)


def generate_qr_token() -> str:
    """Return an opaque, URL-safe token suitable for a printed QR code."""

    return secrets.token_urlsafe(32)


def observation_photo_upload_to(instance, filename: str) -> str:
    """Store photos under their batch with an unguessable server-side name."""

    extension = Path(filename).suffix.lower()
    return (
        f"observation_photos/{instance.batch_id}/"
        f"{uuid.uuid4().hex}{extension}"
    )


def validate_observation_photo_size(photo) -> None:
    """Reject uploads large enough to strain a small self-hosted deployment."""

    if photo.size > MAX_OBSERVATION_PHOTO_BYTES:
        raise ValidationError("Photo files must be 10 MB or smaller.")


class QuantityUnit(models.TextChoices):
    POUND = "lb", "Pounds (lb)"
    OUNCE = "oz", "Ounces (oz)"
    KILOGRAM = "kg", "Kilograms (kg)"
    GRAM = "g", "Grams (g)"
    GALLON = "gal", "Gallons (US)"
    QUART = "qt", "Quarts (US)"
    FLUID_OUNCE = "fl_oz", "Fluid ounces (US)"
    LITER = "L", "Liters (L)"
    MILLILITER = "mL", "Milliliters (mL)"
    CUP = "cup", "Cups"
    TABLESPOON = "tbsp", "Tablespoons"
    TEASPOON = "tsp", "Teaspoons"
    COUNT = "count", "Count"
    OTHER = "other", "Other"


class VolumeUnit(models.TextChoices):
    GALLON = "gal", "Gallons (US)"
    QUART = "qt", "Quarts (US)"
    FLUID_OUNCE = "fl_oz", "Fluid ounces (US)"
    LITER = "L", "Liters (L)"
    MILLILITER = "mL", "Milliliters (mL)"


class TemperatureUnit(models.TextChoices):
    FAHRENHEIT = "F", "°F"
    CELSIUS = "C", "°C"


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet whose normal delete operation is recoverable."""

    def active(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        count = self.update(deleted_at=timezone.now())
        return count, {self.model._meta.label: count}

    def hard_delete(self):
        return super().delete()


class ActiveManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    """Base class for user-authored records that should be recoverable."""

    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = ActiveManager()
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at"])
            return 1, {self._meta.label: 1}
        return 0, {self._meta.label: 0}

    def restore(self):
        if self.deleted_at is not None:
            self.deleted_at = None
            self.save(update_fields=["deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)


class Batch(SoftDeleteModel):
    class Status(models.TextChoices):
        PLANNING = "planning", "Planning"
        FERMENTING = "fermenting", "Fermenting"
        CONDITIONING = "conditioning", "Conditioning"
        AGING = "aging", "Aging"
        BOTTLED = "bottled", "Bottled"
        COMPLETE = "complete", "Complete"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mead_batches",
    )
    name = models.CharField(max_length=160)
    batch_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Optional cellar or production identifier.",
    )
    style = models.CharField(max_length=120, blank=True)
    start_date = models.DateField(default=timezone.localdate)
    fermentation_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Optional exact time fermentation began, such as when yeast was pitched."
        ),
    )
    target_fermentation_sg = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.5000")),
            MaxValueValidator(Decimal("2.0000")),
        ],
        help_text=(
            "Optional target specific gravity used for progress estimates. "
            "It never changes the batch status automatically."
        ),
    )
    planned_conditioning_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(3650),
        ],
        help_text=(
            "Optional planned conditioning window in days. "
            "Reaching it does not change the batch status."
        ),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.FERMENTING,
    )
    volume = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    volume_unit = models.CharField(
        max_length=8,
        choices=VolumeUnit.choices,
        blank=True,
    )
    vessel = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("-start_date", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "batch_number"),
                condition=Q(deleted_at__isnull=True) & ~Q(batch_number=""),
                name="uniq_active_owner_batch_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=("owner", "status", "deleted_at"),
                name="tracker_batch_owner_status",
            ),
            models.Index(fields=("start_date",), name="tracker_batch_started"),
        ]

    def __str__(self) -> str:
        if self.batch_number:
            return f"{self.name} ({self.batch_number})"
        return self.name

    def clean(self):
        super().clean()
        errors = {}
        if self.volume is not None and not self.volume_unit:
            errors["volume_unit"] = "Choose a unit for the batch volume."
        if self.volume_unit and self.volume is None:
            errors["volume"] = "Enter the batch volume."
        if errors:
            raise ValidationError(errors)

    @property
    def age_days(self) -> int:
        """Return the batch age used by both desktop and mobile summaries."""

        return max((timezone.localdate() - self.start_date).days, 0)

    @property
    def latest_gravity(self):
        reading = self.gravity_readings.order_by(
            "-measured_at",
            "-recorded_at",
        ).first()
        return reading.specific_gravity if reading is not None else None

    @property
    def original_gravity(self):
        return (
            self.gravity_readings.filter(
                reading_type=GravityReading.ReadingType.ORIGINAL
            )
            .order_by("measured_at")
            .first()
        )

    @property
    def final_gravity(self):
        return (
            self.gravity_readings.filter(
                reading_type=GravityReading.ReadingType.FINAL
            )
            .order_by("-measured_at")
            .first()
        )

    @property
    def estimated_abv(self):
        """Return the conventional OG/FG ABV estimate, or ``None``."""

        original = self.original_gravity
        final = self.final_gravity
        if original is None or final is None:
            return None
        return (original.specific_gravity - final.specific_gravity) * Decimal(
            "131.25"
        )


class Addition(SoftDeleteModel):
    class Kind(models.TextChoices):
        HONEY = "honey", "Honey"
        WATER = "water", "Water"
        FRUIT = "fruit", "Fruit"
        SPICE = "spice", "Spice or herb"
        YEAST = "yeast", "Yeast"
        NUTRIENT = "nutrient", "Nutrient"
        ACID = "acid", "Acid"
        TANNIN = "tannin", "Tannin"
        FINING = "fining", "Fining agent"
        STABILIZER = "stabilizer", "Stabilizer"
        OTHER = "other", "Other"

    class Phase(models.TextChoices):
        MUST = "must", "Must preparation"
        PRIMARY = "primary", "Primary fermentation"
        SECONDARY = "secondary", "Secondary fermentation"
        CONDITIONING = "conditioning", "Conditioning or aging"
        BOTTLING = "bottling", "Bottling"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="additions",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(
        max_length=160,
        help_text="For example: wildflower honey, orange peel, or D47 yeast.",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    unit = models.CharField(max_length=12, choices=QuantityUnit.choices)
    custom_unit = models.CharField(
        max_length=40,
        blank=True,
        help_text="Required only when the unit is Other.",
    )
    added_at = models.DateTimeField(default=timezone.now)
    phase = models.CharField(
        max_length=20,
        choices=Phase.choices,
        default=Phase.PRIMARY,
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_additions_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("added_at", "recorded_at")
        indexes = [
            models.Index(
                fields=("batch", "added_at", "deleted_at"),
                name="tracker_add_batch_time",
            ),
        ]

    @property
    def display_unit(self) -> str:
        return self.custom_unit if self.unit == QuantityUnit.OTHER else self.get_unit_display()

    def __str__(self) -> str:
        return f"{self.name}: {self.quantity} {self.display_unit}"

    def clean(self):
        super().clean()
        if self.unit == QuantityUnit.OTHER and not self.custom_unit.strip():
            raise ValidationError(
                {"custom_unit": "Describe the unit when Other is selected."}
            )


class GravityReading(SoftDeleteModel):
    class ReadingType(models.TextChoices):
        ORIGINAL = "original", "Original gravity (OG)"
        ROUTINE = "routine", "Routine reading"
        FINAL = "final", "Final gravity (FG)"

    class Method(models.TextChoices):
        HYDROMETER = "hydrometer", "Hydrometer"
        REFRACTOMETER = "refractometer", "Refractometer"
        DIGITAL = "digital", "Digital densitometer"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="gravity_readings",
    )
    specific_gravity = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[
            MinValueValidator(Decimal("0.5000")),
            MaxValueValidator(Decimal("2.0000")),
        ],
        help_text="Enter specific gravity, such as 1.082.",
    )
    reading_type = models.CharField(
        max_length=12,
        choices=ReadingType.choices,
        default=ReadingType.ROUTINE,
    )
    measured_at = models.DateTimeField(default=timezone.now)
    sample_temperature = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-100.00")),
            MaxValueValidator(Decimal("300.00")),
        ],
    )
    temperature_unit = models.CharField(
        max_length=1,
        choices=TemperatureUnit.choices,
        default=TemperatureUnit.FAHRENHEIT,
    )
    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        default=Method.HYDROMETER,
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_gravity_readings_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("measured_at", "recorded_at")
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "reading_type"),
                condition=Q(
                    deleted_at__isnull=True,
                    reading_type__in=(
                        "original",
                        "final",
                    ),
                ),
                name="uniq_active_gravity_role",
            ),
        ]
        indexes = [
            models.Index(
                fields=("batch", "measured_at", "deleted_at"),
                name="tracker_grav_batch_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.specific_gravity} on {self.measured_at:%Y-%m-%d}"

    @property
    def sg(self):
        """Concise display alias used in charts and templates."""

        return self.specific_gravity

    @property
    def value(self):
        return self.specific_gravity

    @property
    def temperature(self):
        return self.sample_temperature


class Observation(SoftDeleteModel):
    class Category(models.TextChoices):
        GENERAL = "general", "General"
        AROMA = "aroma", "Aroma"
        FLAVOR = "flavor", "Flavor"
        APPEARANCE = "appearance", "Appearance"
        FERMENTATION = "fermentation", "Fermentation activity"
        TRANSFER = "transfer", "Transfer or racking"
        ISSUE = "issue", "Potential issue"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="observations",
    )
    observed_at = models.DateTimeField(default=timezone.now)
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    text = models.TextField()
    photo = models.ImageField(
        upload_to=observation_photo_upload_to,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=("jpg", "jpeg", "png", "webp")
            ),
            validate_observation_photo_size,
        ],
        help_text="Optional. Upload a JPEG, PNG, or WebP photo up to 10 MB.",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_observations_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("observed_at", "recorded_at")
        indexes = [
            models.Index(
                fields=("batch", "observed_at", "deleted_at"),
                name="tracker_obs_batch_time",
            ),
        ]

    def __str__(self) -> str:
        preview = self.text[:60]
        return f"{self.get_category_display()}: {preview}"

    def save(self, *args, **kwargs):
        """Remove a replaced photo after the database points at its successor."""

        update_fields = kwargs.get("update_fields")
        photo_may_change = update_fields is None or "photo" in update_fields
        previous_photo_name = ""
        if photo_may_change and self.pk and not self._state.adding:
            previous_photo_name = (
                type(self)
                .all_objects.filter(pk=self.pk)
                .values_list("photo", flat=True)
                .first()
                or ""
            )

        super().save(*args, **kwargs)

        current_photo_name = self.photo.name if self.photo else ""
        if previous_photo_name and previous_photo_name != current_photo_name:
            try:
                self._meta.get_field("photo").storage.delete(previous_photo_name)
            except Exception:
                # File cleanup is best-effort and must not turn a saved journal
                # update into a user-visible failure.
                logger.exception(
                    "Could not delete replaced observation photo %s",
                    previous_photo_name,
                )

    @property
    def created_at(self):
        """Compatibility/display alias for the immutable entry timestamp."""

        return self.recorded_at


class BatchStatusHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    status = models.CharField(max_length=20, choices=Batch.Status.choices)
    changed_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_status_changes",
    )
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("changed_at", "recorded_at")
        indexes = [
            models.Index(
                fields=("batch", "changed_at"),
                name="tracker_status_batch_time",
            ),
        ]
        verbose_name_plural = "batch status history"

    def __str__(self) -> str:
        return f"{self.batch}: {self.get_status_display()}"


class QRLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="qr_links",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_qr_token,
        editable=False,
    )
    label = models.CharField(
        max_length=80,
        blank=True,
        help_text="Optional description, such as 'first bottle run'.",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_qr_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_scanned_at = models.DateTimeField(null=True, blank=True, editable=False)
    scan_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("batch",),
                condition=Q(is_active=True),
                name="uniq_active_qr_per_batch",
            ),
        ]

    def revoke(self):
        if self.is_active:
            self.is_active = False
            self.revoked_at = timezone.now()
            self.save(update_fields=["is_active", "revoked_at"])

    def __str__(self) -> str:
        state = "active" if self.is_active else "revoked"
        return f"{self.batch} QR link ({state})"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Soft deleted"
        RESTORE = "restore", "Restored"
        STATUS = "status", "Status changed"
        QR_ROTATE = "qr_rotate", "QR link rotated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_audit_logs",
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    model_name = models.CharField(max_length=80)
    object_id = models.UUIDField(null=True, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("-recorded_at",)
        indexes = [
            models.Index(
                fields=("batch", "recorded_at"),
                name="tracker_audit_batch_time",
            ),
            models.Index(
                fields=("model_name", "object_id"),
                name="tracker_audit_object",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit log entries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit log entries are immutable.")

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.model_name} at {self.recorded_at}"


class LabelPrintLog(models.Model):
    class DimensionUnit(models.TextChoices):
        INCH = "in", "Inches"
        MILLIMETER = "mm", "Millimeters"

    class OutputMode(models.TextChoices):
        SINGLE = "single", "Single label"
        LETTER_SHEET = "letter", "US Letter sheet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="label_prints",
    )
    qr_link = models.ForeignKey(
        QRLink,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="label_prints",
    )
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mead_labels_printed",
    )
    label_preset = models.CharField(max_length=40, blank=True)
    width = models.DecimalField(
        max_digits=7,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    height = models.DecimalField(
        max_digits=7,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    dimension_unit = models.CharField(
        max_length=2,
        choices=DimensionUnit.choices,
        default=DimensionUnit.INCH,
    )
    output_mode = models.CharField(
        max_length=12,
        choices=OutputMode.choices,
        default=OutputMode.SINGLE,
    )
    copies = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
    )
    printed_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("-printed_at",)
        indexes = [
            models.Index(
                fields=("batch", "printed_at"),
                name="tracker_label_batch_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.batch}: {self.width}×{self.height} {self.dimension_unit}"
