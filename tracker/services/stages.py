from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from decimal import Decimal
from statistics import median

from django.utils import timezone

from tracker.models import Addition, Batch, GravityReading


DISRUPTIVE_ADDITION_KINDS = {
    Addition.Kind.HONEY,
    Addition.Kind.WATER,
    Addition.Kind.FRUIT,
    Addition.Kind.OTHER,
}
TREND_RESET_ADDITION_KINDS = DISRUPTIVE_ADDITION_KINDS | {
    Addition.Kind.YEAST,
    Addition.Kind.NUTRIENT,
    Addition.Kind.STABILIZER,
}
TREND_METHODS = {
    GravityReading.Method.HYDROMETER,
    GravityReading.Method.DIGITAL,
}
MIN_PLAUSIBLE_TARGET_SG = Decimal("0.9000")
MAX_PLAUSIBLE_TARGET_SG = Decimal("1.2000")
MIN_PLAUSIBLE_READING_SG = Decimal("0.8500")
MAX_PLAUSIBLE_READING_SG = Decimal("1.6000")
MAX_FORECAST_DAYS = 90
STALE_READING_DAYS = 7
TREND_LOOKBACK_DAYS = 14


def _active(items):
    return [
        item
        for item in items
        if getattr(item, "deleted_at", None) is None
    ]


def _elapsed_days(started_at: datetime | None, as_of: datetime) -> int:
    if started_at is None or started_at > as_of:
        return 0
    current_zone = timezone.get_current_timezone()
    started_date = timezone.localtime(started_at, current_zone).date()
    as_of_date = timezone.localtime(as_of, current_zone).date()
    return max(0, (as_of_date - started_date).days)


def _elapsed_label(started_at: datetime | None, as_of: datetime) -> str:
    if started_at is None:
        return "Stage start time is not recorded."
    if started_at > as_of:
        return "This stage is scheduled to start later."
    days = _elapsed_days(started_at, as_of)
    if days == 0:
        return "Started this stage today."
    if days == 1:
        return "1 day in this stage."
    return f"{days} days in this stage."


def _stage_entered_at(batch, history, additions, as_of):
    matching = [
        item
        for item in history
        if item.status == batch.status and item.changed_at <= as_of
    ]
    matching.sort(
        key=lambda item: (
            item.changed_at,
            getattr(item, "recorded_at", item.changed_at),
        ),
        reverse=True,
    )
    entered_at = matching[0].changed_at if matching else None

    if batch.status == Batch.Status.FERMENTING:
        explicit_start = getattr(batch, "fermentation_started_at", None)
        if explicit_start is not None:
            return explicit_start

    if entered_at is not None:
        return entered_at
    return None


def _base_result(batch, entered_at, as_of):
    stage_label = batch.get_status_display()
    elapsed_days = _elapsed_days(entered_at, as_of)
    elapsed_label = _elapsed_label(entered_at, as_of)
    return {
        "status": batch.status,
        "stage_label": stage_label,
        "entered_at": entered_at,
        "elapsed_days": elapsed_days,
        "elapsed_label": elapsed_label,
        "ring_mode": "none",
        "progress": None,
        "summary": f"{stage_label} is the currently recorded stage.",
        "accessible_summary": (
            f"{stage_label}. {elapsed_label} No numeric stage estimate."
        ),
        "basis": "This view uses the stage explicitly recorded for the batch.",
        "basis_code": "explicit_status",
        "confidence": "unavailable",
        "forecast_label": "",
        "details": [],
        "prompts": [],
        "original_sg": None,
        "latest_sg": None,
        "target_sg": getattr(batch, "target_fermentation_sg", None),
    }


def _prompt(result, code, message):
    if not any(item["code"] == code for item in result["prompts"]):
        result["prompts"].append({"code": code, "message": message})


def _trend_forecast(readings, target_sg, as_of):
    """Return a broad remaining-time label from a robust local SG trend."""

    usable = sorted(
        (
            item
            for item in readings
            if item.method in TREND_METHODS and item.measured_at <= as_of
        ),
        key=lambda item: (item.measured_at, item.recorded_at),
    )
    if any(
        count > 1
        for count in Counter(
            item.measured_at for item in usable
        ).values()
    ):
        return None
    if len(usable) < 3:
        return None

    latest = usable[-1]
    if (as_of - latest.measured_at).total_seconds() > (
        STALE_READING_DAYS * 86400
    ):
        return None

    distinct = [
        item
        for item in usable
        if (
            latest.measured_at - item.measured_at
        ).total_seconds() <= TREND_LOOKBACK_DAYS * 86400
    ][-5:]
    if len(distinct) < 3:
        return None

    latest_interval_days = (
        distinct[-1].measured_at - distinct[-2].measured_at
    ).total_seconds() / 86400
    if latest_interval_days < 0.25:
        return None
    latest_slope = float(
        distinct[-1].specific_gravity - distinct[-2].specific_gravity
    ) / latest_interval_days
    overall_interval_days = (
        distinct[-1].measured_at - distinct[0].measured_at
    ).total_seconds() / 86400
    if overall_interval_days <= 0:
        return None
    overall_slope = float(
        distinct[-1].specific_gravity - distinct[0].specific_gravity
    ) / overall_interval_days
    if latest_slope >= -0.0001 or overall_slope >= -0.0001:
        return None

    adjacent_slopes = []
    for earlier, later in zip(distinct, distinct[1:]):
        elapsed_days = (
            later.measured_at - earlier.measured_at
        ).total_seconds() / 86400
        if elapsed_days < 0.25:
            return None
        adjacent_slopes.append(
            float(later.specific_gravity - earlier.specific_gravity)
            / elapsed_days
        )
    if any(step > 0.0005 for step in adjacent_slopes):
        return None
    if sum(
        step < -0.0001 for step in adjacent_slopes
    ) < math.ceil(len(adjacent_slopes) * 0.75):
        return None

    slopes = []
    for index, earlier in enumerate(distinct[:-1]):
        for later in distinct[index + 1 :]:
            elapsed_days = (
                later.measured_at - earlier.measured_at
            ).total_seconds() / 86400
            if elapsed_days < 0.25:
                continue
            slopes.append(
                float(later.specific_gravity - earlier.specific_gravity)
                / elapsed_days
            )
    if not slopes:
        return None
    # Fermentation commonly slows. Use the less-negative (slower) of the
    # robust overall trend and the latest interval to avoid optimism.
    slope = max(median(slopes), latest_slope)
    if slope >= -0.0001:
        return None

    remaining_sg = float(latest.specific_gravity - target_sg)
    if remaining_sg <= 0:
        return None
    # Do not assume fermentation continued at the observed rate after the
    # latest sample. The unobserved gap must never make the forecast shorter.
    estimated_days = remaining_sg / -slope
    if not math.isfinite(estimated_days) or not (
        0 < estimated_days <= MAX_FORECAST_DAYS
    ):
        return None

    earliest = max(1, math.floor(estimated_days * 0.75))
    latest_day = max(earliest + 1, math.ceil(estimated_days * 1.5))
    latest_day = min(MAX_FORECAST_DAYS, latest_day)
    return {
        "earliest_days": earliest,
        "latest_days": latest_day,
        "reading_count": len(distinct),
        "label": (
            "From the latest reading, the recent trend suggests roughly "
            f"{earliest}\u2013{latest_day} days to the target reading."
        ),
    }


def _fermentation_result(result, batch, additions, readings, as_of):
    result["ring_mode"] = "unknown"
    result["basis"] = (
        "A fermentation estimate needs an original gravity, a target "
        "fermentation gravity, and a later compatible reading."
    )
    result["basis_code"] = "missing_gravity_inputs"

    if result["entered_at"] is not None and result["entered_at"] > as_of:
        result["summary"] = (
            "Fermentation is scheduled to start later, so progress is not "
            "available yet."
        )
        result["details"].append(
            "The recorded fermentation start is in the future."
        )
        _prompt(
            result,
            "review_status",
            "Review the current stage if fermentation has not started.",
        )
        result["accessible_summary"] = result["summary"]
        return result

    future_readings = [
        item for item in readings if item.measured_at > as_of
    ]
    ordered = sorted(
        (
            item
            for item in readings
            if item.measured_at <= as_of
        ),
        key=lambda item: (item.measured_at, item.recorded_at),
    )
    recorded_original = next(
        (
            item
            for item in ordered
            if item.reading_type == GravityReading.ReadingType.ORIGINAL
        ),
        None,
    )
    latest_recorded = ordered[-1] if ordered else None
    target = getattr(batch, "target_fermentation_sg", None)

    original = None
    if recorded_original is not None:
        method_is_usable = (
            recorded_original.method in TREND_METHODS
            or (
                recorded_original.method
                == GravityReading.Method.REFRACTOMETER
                and result["entered_at"] is not None
                and recorded_original.measured_at <= result["entered_at"]
            )
        )
        value_is_usable = (
            MIN_PLAUSIBLE_READING_SG
            <= recorded_original.specific_gravity
            <= MAX_PLAUSIBLE_READING_SG
        )
        if method_is_usable and value_is_usable:
            original = recorded_original
        else:
            result["details"].append(
                "The recorded original gravity is not usable for this "
                "estimate because its method, timing, or value is unsupported."
            )
    result["original_sg"] = (
        original.specific_gravity if original is not None else None
    )
    result["target_sg"] = target
    if future_readings:
        result["details"].append(
            "Future-dated gravity readings are not used."
        )

    compatible = [
        item
        for item in ordered
        if (
            item.method in TREND_METHODS
            and MIN_PLAUSIBLE_READING_SG
            <= item.specific_gravity
            <= MAX_PLAUSIBLE_READING_SG
        )
    ]
    if result["entered_at"] is not None:
        compatible = [
            item
            for item in compatible
            if item.measured_at >= result["entered_at"]
        ]
    latest_compatible = compatible[-1] if compatible else original
    result["latest_sg"] = (
        latest_compatible.specific_gravity
        if latest_compatible is not None
        else None
    )
    if (
        latest_recorded is not None
        and latest_compatible is not None
        and latest_recorded.measured_at > latest_compatible.measured_at
        and latest_recorded not in compatible
    ):
        result["details"].append(
            "A newer reading is not compatible with this estimate, so "
            "progress uses the older compatible reading."
        )
    excluded_refractometer = [
        item
        for item in ordered
        if (
            item is not original
            and item.method == GravityReading.Method.REFRACTOMETER
            and (
                result["entered_at"] is None
                or item.measured_at >= result["entered_at"]
            )
        )
    ]
    if excluded_refractometer:
        result["details"].append(
            "Post-pitch refractometer readings are excluded because no "
            "alcohol-correction information is recorded."
        )

    if original is None:
        _prompt(
            result,
            "add_original",
            "Record an original gravity to establish the starting point.",
        )
    if target is None:
        _prompt(
            result,
            "set_target",
            "Set a target fermentation SG in the batch details.",
        )
    elif not (
        MIN_PLAUSIBLE_TARGET_SG
        <= target
        <= MAX_PLAUSIBLE_TARGET_SG
    ):
        result["details"].append(
            "The target SG is outside the range supported by this estimate."
        )
        _prompt(
            result,
            "set_target",
            "Review the target fermentation SG.",
        )

    if original is None or target is None:
        result["summary"] = "Progress is unavailable until key gravity inputs are recorded."
        result["accessible_summary"] = (
            f"Fermenting. {result['summary']} {result['elapsed_label']}"
        )
        return result

    disruptive = [
        item
        for item in additions
        if (
            item.kind in DISRUPTIVE_ADDITION_KINDS
            and original.measured_at <= item.added_at <= as_of
        )
    ]
    last_disruptive_at = (
        max(item.added_at for item in disruptive)
        if disruptive
        else None
    )
    trend_reset_additions = [
        item
        for item in additions
        if (
            item.kind in TREND_RESET_ADDITION_KINDS
            and original.measured_at <= item.added_at <= as_of
        )
    ]
    last_trend_reset_at = (
        max(item.added_at for item in trend_reset_additions)
        if trend_reset_additions
        else None
    )

    baseline = original
    segment_readings = compatible
    if last_disruptive_at is not None:
        segment_readings = [
            item
            for item in compatible
            if item.measured_at > last_disruptive_at
        ]
        if segment_readings:
            baseline = segment_readings[0]
            segment_readings = segment_readings[1:]
            result["details"].append(
                "Progress restarts from the first compatible reading after "
                "the latest honey, fruit, water, or other recipe-changing "
                "addition."
            )
        else:
            result["summary"] = (
                "A recipe-changing addition interrupted the gravity trend. "
                "Add a new reading to establish a fresh baseline."
            )
            result["basis"] = (
                "No compatible gravity reading has been recorded since the "
                "latest recipe-changing addition."
            )
            result["basis_code"] = "addition_reset"
            _prompt(
                result,
                "add_reading",
                "Add a hydrometer or digital-density reading after the latest addition.",
            )
            result["accessible_summary"] = result["summary"]
            return result
    else:
        segment_readings = [
            item
            for item in compatible
            if item.measured_at > original.measured_at
        ]

    if not (
        MIN_PLAUSIBLE_TARGET_SG
        <= target
        <= MAX_PLAUSIBLE_TARGET_SG
    ) or target >= baseline.specific_gravity:
        result["summary"] = (
            "The target gravity must be lower than the usable starting "
            "gravity before progress can be estimated."
        )
        result["basis_code"] = "invalid_target"
        _prompt(
            result,
            "set_target",
            "Set a plausible target below the usable starting gravity.",
        )
        result["accessible_summary"] = result["summary"]
        return result

    if not segment_readings:
        result["summary"] = (
            "Add a compatible reading after the starting point to estimate "
            "progress."
        )
        _prompt(
            result,
            "add_reading",
            "Add a hydrometer or digital-density reading.",
        )
        result["accessible_summary"] = result["summary"]
        return result

    if any(
        count > 1
        for count in Counter(
            item.measured_at for item in [baseline, *segment_readings]
        ).values()
    ):
        result["summary"] = (
            "Multiple compatible readings share the same measurement time, "
            "so progress is ambiguous."
        )
        result["basis_code"] = "duplicate_reading_times"
        result["details"].append(
            "Give each gravity reading its actual measurement time before "
            "using the estimate."
        )
        result["accessible_summary"] = result["summary"]
        return result

    latest = segment_readings[-1]
    result["latest_sg"] = latest.specific_gravity
    denominator = baseline.specific_gravity - target
    numerator = baseline.specific_gravity - latest.specific_gravity
    progress = max(
        0,
        min(100, round(float((numerator / denominator) * Decimal("100")))),
    )
    result["ring_mode"] = "gravity"
    result["progress"] = progress
    result["basis"] = (
        "Progress uses the usable starting gravity, latest compatible "
        "reading, and target fermentation SG."
    )
    result["basis_code"] = "gravity"
    result["confidence"] = "limited"
    result["details"].append(
        "Only hydrometer and digital-density readings are used after "
        "fermentation begins."
    )

    if latest.specific_gravity <= target:
        result["summary"] = (
            "At or beyond the target SG. Confirm with stable readings and "
            "your normal process."
        )
        _prompt(
            result,
            "add_reading",
            "Add another reading to confirm the gravity trend.",
        )
        _prompt(
            result,
            "review_status",
            "Review the batch stage when you are satisfied with the readings.",
        )
    elif latest.specific_gravity > baseline.specific_gravity:
        result["summary"] = (
            "The latest compatible gravity is above the usable starting "
            "point, so downward progress is not currently detected."
        )
    else:
        result["summary"] = f"About {progress}% toward the target SG."

    trend_inputs = [baseline, *segment_readings]
    if last_trend_reset_at is not None:
        trend_inputs = [
            item
            for item in trend_inputs
            if item.measured_at > last_trend_reset_at
        ]
    forecast = _trend_forecast(trend_inputs, target, as_of)
    if forecast is not None:
        result["forecast_label"] = forecast["label"]
        result["confidence"] = "trend"
        result["details"].append(
            f"The broad time window uses {forecast['reading_count']} "
            "compatible readings and may widen as fermentation slows."
        )
    elif latest.specific_gravity > target:
        if (
            as_of - latest.measured_at
        ).total_seconds() > STALE_READING_DAYS * 86400:
            result["details"].append(
                "The latest compatible reading is more than seven days old, "
                "so no time forecast is shown."
            )
        else:
            result["details"].append(
                "At least three recent readings with a reliable downward "
                "trend are needed for a time forecast."
            )
        _prompt(
            result,
            "add_reading",
            "Keep recording gravity to build a usable recent trend.",
        )

    result["accessible_summary"] = (
        f"Fermenting. {result['summary']} "
        f"{result['forecast_label']} {result['elapsed_label']}"
    ).strip()
    return result


def build_stage_visual(
    batch,
    *,
    additions=None,
    gravity_readings=None,
    status_history=None,
    as_of: datetime | None = None,
):
    """Build an advisory, stage-aware visual summary without changing data."""

    as_of = as_of or timezone.now()
    if timezone.is_naive(as_of):
        as_of = timezone.make_aware(as_of, timezone.get_current_timezone())

    if additions is None:
        additions = batch.additions.all()
    if gravity_readings is None:
        gravity_readings = batch.gravity_readings.all()
    if status_history is None:
        status_history = batch.status_history.all()

    additions = _active(list(additions))
    readings = _active(list(gravity_readings))
    history = list(status_history)
    entered_at = _stage_entered_at(
        batch,
        history,
        additions,
        as_of,
    )
    result = _base_result(batch, entered_at, as_of)

    if batch.status == Batch.Status.PLANNING:
        result["summary"] = "Planning is open-ended, so no progress ring is shown."
        result["basis_code"] = "planning"
    elif batch.status == Batch.Status.FERMENTING:
        return _fermentation_result(
            result,
            batch,
            additions,
            readings,
            as_of,
        )
    elif batch.status == Batch.Status.CONDITIONING:
        planned_days = getattr(batch, "planned_conditioning_days", None)
        has_valid_plan = (
            isinstance(planned_days, int)
            and not isinstance(planned_days, bool)
            and 0 < planned_days <= 3650
        )
        if result["entered_at"] is not None and has_valid_plan:
            progress = max(
                0,
                min(
                    100,
                    round((result["elapsed_days"] / planned_days) * 100),
                ),
            )
            result["ring_mode"] = "planned"
            result["progress"] = progress
            result["summary"] = (
                f"Day {result['elapsed_days']} of your "
                f"{planned_days}-day conditioning plan."
            )
            result["basis"] = (
                "This is elapsed time within the conditioning window you "
                "entered; it is not a fermentation measurement."
            )
            result["basis_code"] = "conditioning_plan"
            result["confidence"] = "limited"
            if progress >= 100:
                result["forecast_label"] = (
                    "The planned window has been reached; the stage does not "
                    "change automatically."
                )
                _prompt(
                    result,
                    "review_status",
                    "Review the batch when you are ready to choose its next stage.",
                )
        elif has_valid_plan:
            result["summary"] = (
                f"A {planned_days}-day conditioning plan is set, but the "
                "conditioning start time is not recorded."
            )
            result["basis"] = (
                "Planned conditioning progress needs both the window you "
                "entered and a recorded start for the conditioning stage."
            )
            result["basis_code"] = "missing_conditioning_start"
            _prompt(
                result,
                "review_status",
                "Review the conditioning stage to establish its start time.",
            )
        else:
            result["summary"] = (
                "Conditioning is open-ended because no planned window is set."
            )
            result["basis_code"] = "open_conditioning"
    elif batch.status == Batch.Status.AGING:
        result["summary"] = (
            f"Aging is open-ended. {result['elapsed_label']} "
            "No progress ring is shown."
        )
        result["basis_code"] = "open_aging"
    elif batch.status in {
        Batch.Status.BOTTLED,
        Batch.Status.COMPLETE,
    }:
        result["ring_mode"] = "complete"
        result["summary"] = (
            f"{result['stage_label']} is the status you explicitly recorded."
        )
        result["basis_code"] = "terminal_status"
    elif batch.status == Batch.Status.ARCHIVED:
        result["summary"] = "Archived batches do not display stage progress."
        result["basis_code"] = "archived"

    result["accessible_summary"] = (
        f"{result['stage_label']}. {result['summary']} "
        f"{result['elapsed_label']}"
    ).strip()
    return result
