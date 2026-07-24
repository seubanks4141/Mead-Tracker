"""Forms and user-facing validation for Mead Tracker records."""

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.utils import timezone

from .models import (
    Addition,
    Batch,
    BatchStatusHistory,
    GravityReading,
    LabelPrintLog,
    Observation,
    QuantityUnit,
)


class LocalDateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%dT%H:%M")
        super().__init__(*args, **kwargs)


class StyledFormMixin:
    """Apply framework-neutral CSS hooks while retaining widget overrides."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css_class = "form-check-input"
            else:
                css_class = "form-select" if isinstance(widget, forms.Select) else "form-control"
            current = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{current} {css_class}".strip()


class UserCreateForm(StyledFormMixin, UserCreationForm):
    """Create an active, non-privileged account with Django password checks."""

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class SignupForm(UserCreateForm):
    """Public signup form; intentionally exposes no permission fields."""


class BatchForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Batch
        fields = (
            "name",
            "batch_number",
            "style",
            "start_date",
            "fermentation_started_at",
            "target_fermentation_sg",
            "planned_conditioning_days",
            "volume",
            "volume_unit",
            "vessel",
            "description",
        )
        labels = {
            "fermentation_started_at": "Fermentation started",
            "target_fermentation_sg": "Target fermentation SG",
            "planned_conditioning_days": "Planned conditioning window (days)",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "fermentation_started_at": LocalDateTimeInput(),
            "target_fermentation_sg": forms.NumberInput(
                attrs={
                    "step": "0.0001",
                    "inputmode": "decimal",
                    "placeholder": "1.000",
                }
            ),
            "planned_conditioning_days": forms.NumberInput(
                attrs={"step": "1", "min": "1", "inputmode": "numeric"}
            ),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        if owner is None and self.instance.owner_id:
            owner = self.instance.owner
        self.owner = owner
        self.fields["fermentation_started_at"].input_formats = (
            "%Y-%m-%dT%H:%M",
        )

    def clean_batch_number(self):
        batch_number = self.cleaned_data.get("batch_number", "").strip()
        if batch_number and self.owner is not None:
            matching = Batch.objects.filter(
                owner=self.owner,
                batch_number=batch_number,
            ).exclude(pk=self.instance.pk)
            if matching.exists():
                raise forms.ValidationError(
                    "You already have an active batch with this batch number."
                )
        return batch_number

    def save(self, commit=True):
        batch = super().save(commit=False)
        if self.owner is not None:
            batch.owner = self.owner
        if commit:
            batch.save()
            self.save_m2m()
        return batch


class AdditionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Addition
        fields = (
            "kind",
            "name",
            "quantity",
            "unit",
            "custom_unit",
            "added_at",
            "phase",
            "notes",
        )
        widgets = {
            "added_at": LocalDateTimeInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["added_at"].input_formats = ("%Y-%m-%dT%H:%M",)

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get("unit")
        if unit != QuantityUnit.OTHER:
            cleaned["custom_unit"] = ""
        return cleaned


class GravityReadingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GravityReading
        fields = (
            "specific_gravity",
            "reading_type",
            "measured_at",
            "sample_temperature",
            "temperature_unit",
            "method",
            "notes",
        )
        widgets = {
            "measured_at": LocalDateTimeInput(),
            "specific_gravity": forms.NumberInput(
                attrs={"step": "0.0001", "inputmode": "decimal", "placeholder": "1.082"}
            ),
            "sample_temperature": forms.NumberInput(
                attrs={"step": "0.1", "inputmode": "decimal"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["measured_at"].input_formats = ("%Y-%m-%dT%H:%M",)


class ObservationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Observation
        fields = ("observed_at", "category", "text")
        widgets = {
            "observed_at": LocalDateTimeInput(),
            "text": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Record aromas, flavor, appearance, activity, or anything else you notice.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["observed_at"].input_formats = ("%Y-%m-%dT%H:%M",)


class BatchStatusForm(StyledFormMixin, forms.ModelForm):
    """Create a status-history row and keep ``Batch.status`` in sync.

    Pass the target batch at construction time and the request user to
    ``save(changed_by=...)``.
    """

    class Meta:
        model = BatchStatusHistory
        fields = ("status", "changed_at", "notes")
        widgets = {
            "changed_at": LocalDateTimeInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, batch=None, **kwargs):
        self.batch = batch
        super().__init__(*args, **kwargs)
        self.fields["changed_at"].input_formats = ("%Y-%m-%dT%H:%M",)
        if batch is not None and not self.is_bound:
            self.initial.setdefault("status", batch.status)

    def clean_status(self):
        status = self.cleaned_data["status"]
        if (
            self.batch is not None
            and status == self.batch.status
            and BatchStatusHistory.objects.filter(
                batch=self.batch,
                status=status,
            ).exists()
        ):
            raise forms.ValidationError(
                "Choose a different status for this batch."
            )
        return status

    def save(self, commit=True, changed_by=None):
        history = super().save(commit=False)
        if self.batch is None:
            raise ValueError("BatchStatusForm requires batch= before it can be saved.")
        history.batch = self.batch
        history.changed_by = changed_by
        if not commit:
            return history
        with transaction.atomic():
            history.save()
            latest = (
                BatchStatusHistory.objects.filter(batch=self.batch)
                .order_by("-changed_at", "-recorded_at")
                .first()
            )
            Batch.all_objects.filter(pk=self.batch.pk).update(
                status=latest.status,
                updated_at=timezone.now(),
            )
            self.batch.status = latest.status
        return history


class ConfirmDeleteForm(StyledFormMixin, forms.Form):
    confirm = forms.BooleanField(
        label="I understand this record will be removed from normal views.",
        required=True,
    )


class LabelSizeForm(StyledFormMixin, forms.Form):
    PRESET_2_5_X_3 = "2.5x3"
    PRESET_3_X_4 = "3x4"
    PRESET_3_333_X_4 = "3.333x4"
    PRESET_CUSTOM = "custom"

    PRESET_CHOICES = (
        (PRESET_3_X_4, '3 × 4 inches'),
        (PRESET_2_5_X_3, '2½ × 3 inches'),
        (PRESET_3_333_X_4, '3⅓ × 4 inches'),
        (PRESET_CUSTOM, "Custom size"),
    )
    PRESET_DIMENSIONS = {
        PRESET_2_5_X_3: (Decimal("2.500"), Decimal("3.000")),
        PRESET_3_X_4: (Decimal("3.000"), Decimal("4.000")),
        PRESET_3_333_X_4: (Decimal("3.333"), Decimal("4.000")),
    }

    preset = forms.ChoiceField(choices=PRESET_CHOICES, initial=PRESET_3_X_4)
    width = forms.DecimalField(
        required=False,
        min_value=Decimal("0.001"),
        max_digits=7,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"step": "0.001", "inputmode": "decimal"}),
    )
    height = forms.DecimalField(
        required=False,
        min_value=Decimal("0.001"),
        max_digits=7,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"step": "0.001", "inputmode": "decimal"}),
    )
    dimension_unit = forms.ChoiceField(
        choices=LabelPrintLog.DimensionUnit.choices,
        initial=LabelPrintLog.DimensionUnit.INCH,
    )
    output_mode = forms.ChoiceField(
        choices=LabelPrintLog.OutputMode.choices,
        initial=LabelPrintLog.OutputMode.SINGLE,
    )
    copies = forms.IntegerField(min_value=1, max_value=100, initial=1)
    include_batch_number = forms.BooleanField(required=False, initial=True)

    def clean(self):
        cleaned = super().clean()
        preset = cleaned.get("preset")
        if preset in self.PRESET_DIMENSIONS:
            cleaned["width"], cleaned["height"] = self.PRESET_DIMENSIONS[preset]
            cleaned["dimension_unit"] = LabelPrintLog.DimensionUnit.INCH
            return cleaned

        width = cleaned.get("width")
        height = cleaned.get("height")
        unit = cleaned.get("dimension_unit")
        if width is None:
            self.add_error("width", "Enter a custom label width.")
        if height is None:
            self.add_error("height", "Enter a custom label height.")
        if width is None or height is None:
            return cleaned

        max_dimension = (
            Decimal("12")
            if unit == LabelPrintLog.DimensionUnit.INCH
            else Decimal("305")
        )
        min_width = (
            Decimal("2.5")
            if unit == LabelPrintLog.DimensionUnit.INCH
            else Decimal("63.5")
        )
        min_height = (
            Decimal("3")
            if unit == LabelPrintLog.DimensionUnit.INCH
            else Decimal("76.2")
        )
        if not min_width <= width <= max_dimension:
            self.add_error(
                "width",
                f"Custom width must be between {min_width} and {max_dimension} {unit}.",
            )
        if not min_height <= height <= max_dimension:
            self.add_error(
                "height",
                f"Custom height must be between {min_height} and {max_dimension} {unit}.",
            )
        if cleaned.get("output_mode") == LabelPrintLog.OutputMode.LETTER_SHEET:
            max_sheet_width = (
                Decimal("8")
                if unit == LabelPrintLog.DimensionUnit.INCH
                else Decimal("203.2")
            )
            max_sheet_height = (
                Decimal("10.5")
                if unit == LabelPrintLog.DimensionUnit.INCH
                else Decimal("266.7")
            )
            if width > max_sheet_width:
                self.add_error(
                    "width",
                    "This label is too wide for the printable US Letter proof sheet.",
                )
            if height > max_sheet_height:
                self.add_error(
                    "height",
                    "This label is too tall for the printable US Letter proof sheet.",
                )
        return cleaned
