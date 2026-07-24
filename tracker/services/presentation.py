from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone


# Every color exposed by ``build_visual_mark`` comes from this fixed table.
# User-entered ingredient names never become CSS values or visual labels.
INGREDIENT_KIND_VISUALS = {
    "honey": {
        "label": "Honey",
        "colors": ("#C98222", "#F2C15D", "#8B4513", "#4A2916"),
    },
    "water": {
        "label": "Water",
        "colors": ("#4E91A8", "#9AC9D4", "#2F6678", "#193A45"),
    },
    "fruit": {
        "label": "Fruit",
        "colors": ("#A94B55", "#E58B83", "#71313D", "#3E2028"),
    },
    "spice": {
        "label": "Spice or herb",
        "colors": ("#A65F2B", "#DFA46D", "#6E3B20", "#3C2418"),
    },
    "yeast": {
        "label": "Yeast",
        "colors": ("#927342", "#D3BC83", "#5E4A2D", "#332A1E"),
    },
    "nutrient": {
        "label": "Nutrient",
        "colors": ("#788D3E", "#B6C879", "#4F5F28", "#2D371B"),
    },
    "acid": {
        "label": "Acid",
        "colors": ("#B7A329", "#E4D66D", "#766B1F", "#423C17"),
    },
    "tannin": {
        "label": "Tannin",
        "colors": ("#70452F", "#B18467", "#4A2B20", "#2A1B16"),
    },
    "fining": {
        "label": "Fining agent",
        "colors": ("#8A8175", "#C9C2B8", "#5B544C", "#302D29"),
    },
    "stabilizer": {
        "label": "Stabilizer",
        "colors": ("#687D78", "#A9BBB5", "#445550", "#27322F"),
    },
    "other": {
        "label": "Other",
        "colors": ("#74618C", "#B8A6CB", "#4D3D61", "#2C2437"),
    },
}

VISUAL_MARK_SHAPES = ("drop", "round", "hex", "shield", "bloom", "pebble")


def _age_stage(age_days: int) -> str:
    if age_days < 14:
        return "new"
    if age_days < 60:
        return "developing"
    if age_days < 180:
        return "conditioning"
    if age_days < 365:
        return "aging"
    return "mature"


def build_visual_mark(
    batch,
    *,
    additions=None,
    on_date: date | None = None,
) -> dict:
    """Return a stable, CSS-safe visual identity for one batch.

    The identity uses only a batch UUID and canonical ingredient-kind choices.
    Age and production stage are deliberately excluded so the center remains
    recognizable while the separate stage treatment changes. Ingredient
    names and other free text are never included. Passing ``on_date`` keeps
    the informational age metadata straightforward to test.
    """

    if additions is None:
        additions = batch.additions.all()
    canonical_kinds = sorted(
        {
            kind if kind in INGREDIENT_KIND_VISUALS else "other"
            for kind in (
                getattr(item, "kind", "other")
                for item in additions
                if getattr(item, "deleted_at", None) is None
            )
        }
    )
    if not canonical_kinds:
        canonical_kinds = ["other"]

    current_date = on_date or timezone.localdate()
    age_days = max(0, (current_date - batch.start_date).days)
    age_bucket = age_days // 30
    seed_text = f"{batch.pk}|{','.join(canonical_kinds)}".encode("ascii")
    digest = hashlib.sha256(seed_text).digest()

    palette_entries = [
        INGREDIENT_KIND_VISUALS[kind] for kind in canonical_kinds
    ]
    palette = {
        "primary": palette_entries[digest[4] % len(palette_entries)]["colors"][0],
        "highlight": palette_entries[digest[5] % len(palette_entries)]["colors"][1],
        "accent": palette_entries[digest[6] % len(palette_entries)]["colors"][2],
        "ink": palette_entries[digest[7] % len(palette_entries)]["colors"][3],
    }

    marker_kinds = canonical_kinds[:4]
    ingredient_markers = []
    for index, kind in enumerate(marker_kinds):
        visual = INGREDIENT_KIND_VISUALS[kind]
        offset = 8 + index * 5
        ingredient_markers.append(
            {
                "kind": kind,
                "label": visual["label"],
                "color": visual["colors"][2],
                "shape": 1 + digest[offset] % 4,
                "rotation": -24 + digest[offset + 1] % 49,
                "scale": round(0.78 + (digest[offset + 2] / 255) * 0.34, 3),
                "orbit": 30 + digest[offset + 3] % 27,
                "angle": digest[offset + 4] % 360,
            }
        )

    age_progress = round(min(age_days / 365, 1) * 100, 2)
    return {
        "shape": VISUAL_MARK_SHAPES[digest[0] % len(VISUAL_MARK_SHAPES)],
        "rotation": -16 + digest[1] % 33,
        "scale": round(0.9 + (digest[2] / 255) * 0.2, 3),
        "roundness": 40 + digest[3] % 33,
        "color_start": palette["primary"],
        "color_end": palette["accent"],
        "glow_color": palette["highlight"],
        "palette": palette,
        "age_days": age_days,
        "age_bucket": age_bucket,
        "age_stage": _age_stage(age_days),
        "age_progress": age_progress,
        "ring_count": min(6, 1 + age_days // 90),
        "ring_spacing": round(6 + age_progress * 0.06, 2),
        "ring_opacity": round(0.12 + age_progress * 0.0028, 3),
        "texture_density": round(8 + age_progress * 0.28, 2),
        "texture_rotation": -30 + digest[28] % 61,
        "ingredient_labels": [
            INGREDIENT_KIND_VISUALS[kind]["label"] for kind in marker_kinds
        ],
        "ingredient_markers": ingredient_markers,
    }


def build_activity(
    batch,
    *,
    include_deleted: bool = False,
    additions=None,
    gravity_readings=None,
    observations=None,
    status_history=None,
) -> list[dict]:
    """Combine batch records into one reverse-chronological timeline."""

    manager_name = "all_objects" if include_deleted else "objects"
    entries: list[dict] = []

    if additions is None:
        if include_deleted:
            additions = batch.additions.model.all_objects.filter(batch=batch)
        else:
            additions = batch.additions.all()
    for item in additions:
        entries.append(
            {
                "kind": "addition",
                "pk": item.pk,
                "timestamp": item.added_at,
                "eyebrow": item.get_kind_display(),
                "title": f"{item.quantity:g} {item.display_unit} {item.name}",
                "detail": item.notes,
                "summary": item.notes,
                "description": item.notes,
                "batch": batch,
                "object": item,
                "deleted": bool(item.deleted_at),
                "deleted_at": item.deleted_at,
                "edit_url": reverse(
                    "tracker:addition_edit",
                    kwargs={"pk": item.pk},
                ),
            }
        )

    if gravity_readings is None:
        gravity_readings = getattr(
            batch.gravity_readings.model,
            manager_name,
        ).filter(batch=batch)
    for item in gravity_readings:
        detail_parts = [item.get_method_display()]
        if item.sample_temperature is not None:
            detail_parts.append(
                f"{item.sample_temperature:g}°{item.temperature_unit}"
            )
        if item.notes:
            detail_parts.append(item.notes)
        entries.append(
            {
                "kind": "gravity",
                "pk": item.pk,
                "timestamp": item.measured_at,
                "eyebrow": item.get_reading_type_display(),
                "title": f"Specific gravity {item.specific_gravity}",
                "detail": " · ".join(detail_parts),
                "summary": " · ".join(detail_parts),
                "description": " · ".join(detail_parts),
                "batch": batch,
                "object": item,
                "deleted": bool(item.deleted_at),
                "deleted_at": item.deleted_at,
                "edit_url": reverse(
                    "tracker:gravity_edit",
                    kwargs={"pk": item.pk},
                ),
            }
        )

    if observations is None:
        observations = getattr(
            batch.observations.model,
            manager_name,
        ).filter(batch=batch)
    for item in observations:
        entries.append(
            {
                "kind": "observation",
                "pk": item.pk,
                "timestamp": item.observed_at,
                "eyebrow": item.get_category_display(),
                "title": "Observation",
                "detail": item.text,
                "summary": item.text,
                "description": item.text,
                "batch": batch,
                "object": item,
                "deleted": bool(item.deleted_at),
                "deleted_at": item.deleted_at,
                "edit_url": reverse(
                    "tracker:observation_edit",
                    kwargs={"pk": item.pk},
                ),
            }
        )

    if not include_deleted:
        if status_history is None:
            status_history = batch.status_history.all()
        for item in status_history:
            entries.append(
                {
                    "kind": "status",
                    "pk": item.pk,
                    "timestamp": item.changed_at,
                    "eyebrow": "Status",
                    "title": item.get_status_display(),
                    "detail": item.notes,
                    "summary": item.notes,
                    "description": item.notes,
                    "batch": batch,
                    "object": item,
                    "deleted": False,
                    "deleted_at": None,
                    "edit_url": "",
                }
            )

    return sorted(entries, key=lambda item: item["timestamp"], reverse=True)


def build_gravity_summary(batch) -> dict:
    readings = list(batch.gravity_readings.order_by("measured_at", "recorded_at"))
    latest = readings[-1] if readings else None
    original = next(
        (
            reading
            for reading in readings
            if reading.reading_type == reading.ReadingType.ORIGINAL
        ),
        None,
    )
    final = next(
        (
            reading
            for reading in reversed(readings)
            if reading.reading_type == reading.ReadingType.FINAL
        ),
        None,
    )

    live_abv = None
    final_abv = None
    if original and latest and latest.pk != original.pk:
        live_abv = max(
            Decimal("0"),
            (original.specific_gravity - latest.specific_gravity)
            * Decimal("131.25"),
        ).quantize(Decimal("0.1"))
    if original and final:
        final_abv = max(
            Decimal("0"),
            (original.specific_gravity - final.specific_gravity)
            * Decimal("131.25"),
        ).quantize(Decimal("0.1"))

    chart = {
        "labels": [
            timezone.localtime(reading.measured_at).strftime("%b %d, %Y %H:%M")
            for reading in readings
        ],
        "values": [float(reading.specific_gravity) for reading in readings],
    }
    return {
        "readings": readings,
        "latest": latest,
        "original": original,
        "final": final,
        "live_abv": live_abv,
        "final_abv": final_abv,
        "chart": chart,
    }
