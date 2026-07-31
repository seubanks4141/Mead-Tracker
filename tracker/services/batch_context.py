"""Canonical, owner-scoped batch context for exports and AI tools."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Prefetch
from django.utils import timezone

from tracker.models import (
    Addition,
    Batch,
    BatchStatusHistory,
    GravityReading,
    Observation,
)


BATCH_CONTEXT_FORMAT = "mead-tracker-batch"
BATCH_CONTEXT_VERSION = 1


def _addition_data(item: Addition) -> dict:
    return {
        "id": item.pk,
        "kind": item.kind,
        "name": item.name,
        "quantity": item.quantity,
        "unit": item.unit,
        "custom_unit": item.custom_unit,
        "phase": item.phase,
        "added_at": item.added_at,
        "notes": item.notes,
        "recorded_at": item.recorded_at,
        "updated_at": item.updated_at,
    }


def _gravity_data(item: GravityReading) -> dict:
    return {
        "id": item.pk,
        "specific_gravity": item.specific_gravity,
        "reading_type": item.reading_type,
        "measured_at": item.measured_at,
        "recorded_at": item.recorded_at,
        "sample_temperature": item.sample_temperature,
        "temperature_unit": item.temperature_unit,
        "method": item.method,
        "notes": item.notes,
        "updated_at": item.updated_at,
    }


def _observation_data(item: Observation) -> dict:
    return {
        "id": item.pk,
        "observed_at": item.observed_at,
        "recorded_at": item.recorded_at,
        "category": item.category,
        "text": item.text,
        "updated_at": item.updated_at,
        "has_photo": bool(item.photo),
    }


def _status_data(item: BatchStatusHistory) -> dict:
    return {
        "id": item.pk,
        "status": item.status,
        "changed_at": item.changed_at,
        "notes": item.notes,
        "recorded_at": item.recorded_at,
    }


def _gravity_summary(readings: list[GravityReading]) -> dict:
    latest = readings[-1] if readings else None
    original = next(
        (
            reading
            for reading in readings
            if reading.reading_type == GravityReading.ReadingType.ORIGINAL
        ),
        None,
    )
    final = next(
        (
            reading
            for reading in reversed(readings)
            if reading.reading_type == GravityReading.ReadingType.FINAL
        ),
        None,
    )

    estimated_abv = None
    estimated_abv_is_final = False
    if original is not None and final is not None:
        estimated_abv = max(
            Decimal("0"),
            (original.specific_gravity - final.specific_gravity) * Decimal("131.25"),
        ).quantize(Decimal("0.1"))
        estimated_abv_is_final = True
    elif original is not None and latest is not None and latest.pk != original.pk:
        estimated_abv = max(
            Decimal("0"),
            (original.specific_gravity - latest.specific_gravity)
            * Decimal("131.25"),
        ).quantize(Decimal("0.1"))

    return {
        "latest_gravity": latest.specific_gravity if latest is not None else None,
        "original_gravity": (
            original.specific_gravity if original is not None else None
        ),
        "final_gravity": final.specific_gravity if final is not None else None,
        "estimated_abv": estimated_abv,
        "estimated_abv_is_final": estimated_abv_is_final,
    }


def _content_revision(batch_data: dict) -> str:
    canonical = json.dumps(
        batch_data,
        cls=DjangoJSONEncoder,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _json_native(value):
    """Normalize Django values for direct use in JSON or an MCP tool result."""

    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))


def build_batch_context(batch: Batch, *, generated_at=None) -> dict:
    """Build the allowlisted context for one already-authorized active batch.

    Callers that start with an untrusted batch ID should use
    :func:`get_owned_batch_context`, which applies the owner boundary before
    returning any data.
    """

    additions = list(batch.additions.all())
    gravity_readings = list(batch.gravity_readings.all())
    observations = list(batch.observations.all())
    status_history = list(batch.status_history.all())

    batch_data = {
        "id": batch.pk,
        "name": batch.name,
        "batch_number": batch.batch_number,
        "style": batch.style,
        "start_date": batch.start_date,
        "fermentation_started_at": batch.fermentation_started_at,
        "target_fermentation_sg": batch.target_fermentation_sg,
        "planned_conditioning_days": batch.planned_conditioning_days,
        "status": batch.status,
        "volume": batch.volume,
        "volume_unit": batch.volume_unit,
        "vessel": batch.vessel,
        "description": batch.description,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "summary": _gravity_summary(gravity_readings),
        "additions": [_addition_data(item) for item in additions],
        "gravity_readings": [_gravity_data(item) for item in gravity_readings],
        "observations": [_observation_data(item) for item in observations],
        "status_history": [_status_data(item) for item in status_history],
    }
    return _json_native(
        {
            "format": BATCH_CONTEXT_FORMAT,
            "version": BATCH_CONTEXT_VERSION,
            "exported_at": generated_at or timezone.now(),
            "content_revision": _content_revision(batch_data),
            "batch": batch_data,
        }
    )


def get_owned_batch_context(*, owner, batch_id, generated_at=None) -> dict:
    """Return fresh context only when ``batch_id`` belongs to an active owner.

    Missing, removed, and foreign batches all raise ``Batch.DoesNotExist`` so
    callers do not disclose whether another account owns a supplied UUID.
    """

    batch = (
        Batch.objects.filter(owner=owner, owner__is_active=True)
        .prefetch_related(
            Prefetch(
                "additions",
                queryset=Addition.objects.order_by("added_at", "recorded_at", "pk"),
            ),
            Prefetch(
                "gravity_readings",
                queryset=GravityReading.objects.order_by(
                    "measured_at",
                    "recorded_at",
                    "pk",
                ),
            ),
            Prefetch(
                "observations",
                queryset=Observation.objects.order_by(
                    "observed_at",
                    "recorded_at",
                    "pk",
                ),
            ),
            Prefetch(
                "status_history",
                queryset=BatchStatusHistory.objects.order_by(
                    "changed_at",
                    "recorded_at",
                    "pk",
                ),
            ),
        )
        .get(pk=batch_id)
    )
    return build_batch_context(batch, generated_at=generated_at)
