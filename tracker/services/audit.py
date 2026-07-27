"""Small helpers for recording explicit, actor-aware audit entries."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.db import models
from django.db.models.fields.files import FieldFile

from tracker.models import AuditLog, Batch


def _json_value(value):
    if isinstance(value, (dt.date, dt.datetime, dt.time, Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name
    if isinstance(value, models.Model):
        return str(value.pk)
    return value


def snapshot(instance, *, exclude=()):
    """Return a JSON-safe snapshot of concrete model fields."""

    excluded = set(exclude)
    values = {}
    for field in instance._meta.concrete_fields:
        if field.name in excluded:
            continue
        values[field.name] = _json_value(getattr(instance, field.attname))
    return values


def changes_between(before, after):
    """Return only changed keys, represented as before/after values."""

    keys = before.keys() | after.keys()
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in keys
        if before.get(key) != after.get(key)
    }


def record_audit(
    *,
    action,
    instance,
    actor=None,
    batch=None,
    changes=None,
):
    """Create an immutable audit entry for an already-authorized action."""

    if batch is None:
        batch = instance if isinstance(instance, Batch) else getattr(instance, "batch", None)
    return AuditLog.objects.create(
        batch=batch,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        model_name=instance._meta.label_lower,
        object_id=instance.pk,
        object_repr=str(instance)[:255],
        changes=changes or {},
    )
