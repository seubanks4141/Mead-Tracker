from __future__ import annotations

import json
import mimetypes
from io import BytesIO
from urllib.parse import urlparse

import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, F, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    AdditionForm,
    BatchForm,
    BatchStatusForm,
    ConfirmDeleteForm,
    GravityReadingForm,
    LabelSizeForm,
    ObservationForm,
    SignupForm,
    UserCreateForm,
)
from .models import (
    Addition,
    AuditLog,
    Batch,
    BatchStatusHistory,
    GravityReading,
    LabelPrintLog,
    Observation,
    QRLink,
)
from .services.audit import changes_between, record_audit, snapshot
from .services.backups import BackupError, create_backup_bytes
from .services.batch_context import get_owned_batch_context
from .services.labels import render_label_pdf
from .services.presentation import (
    build_activity,
    build_gravity_summary,
    build_visual_mark,
)
from .services.stages import build_stage_visual


ENTRY_TYPES = {
    "addition": (Addition, AdditionForm, "ingredient addition"),
    "gravity": (GravityReading, GravityReadingForm, "gravity reading"),
    "observation": (Observation, ObservationForm, "observation"),
}


def _require_superuser(request) -> None:
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied("Only a superuser can manage user accounts.")


def _safe_next_url(request) -> str:
    candidate = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ""


def _record_user_audit(*, action, target, actor, changes) -> None:
    """Record account changes without forcing integer user IDs into UUID fields."""

    AuditLog.objects.create(
        actor=actor,
        action=action,
        model_name=target._meta.label_lower,
        object_id=None,
        object_repr=f"{target.get_username()} (user {target.pk})"[:255],
        changes=changes,
    )


def _revoke_user_sessions(user_id) -> int:
    """Delete every live database session belonging to one account."""

    session_ids = []
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        session_user_id = session.get_decoded().get("_auth_user_id")
        if str(session_user_id) == str(user_id):
            session_ids.append(session.pk)
    if not session_ids:
        return 0
    deleted, _ = Session.objects.filter(pk__in=session_ids).delete()
    return deleted


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unhealthy"}, status=503)
    return JsonResponse({"status": "ok"})


def signup(request):
    if not getattr(settings, "ALLOW_SIGNUPS", False):
        raise Http404("Signups are not enabled.")

    next_url = _safe_next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or "tracker:dashboard")

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            _record_user_audit(
                action=AuditLog.Action.CREATE,
                target=user,
                actor=user,
                changes={
                    "created": {
                        "user_id": user.pk,
                        "username": user.get_username(),
                        "is_active": user.is_active,
                        "source": "public_signup",
                    }
                },
            )
        auth_login(request, user)
        messages.success(request, "Your Mead Tracker account is ready.")
        return redirect(next_url or "tracker:dashboard")

    return render(
        request,
        "registration/signup.html",
        {
            "form": form,
            "next": next_url,
            "allow_signups": True,
        },
    )


@login_required
def user_list(request):
    _require_superuser(request)
    User = get_user_model()
    users = User._default_manager.annotate(
        active_batch_count=Count(
            "mead_batches",
            filter=Q(mead_batches__deleted_at__isnull=True),
            distinct=True,
        ),
        total_batch_count=Count("mead_batches", distinct=True),
    ).order_by("-is_active", "-is_superuser", "username")
    return render(
        request,
        "tracker/user_list.html",
        {
            "users": users,
            "active_user_count": User._default_manager.filter(is_active=True).count(),
            "total_user_count": User._default_manager.count(),
            "allow_signups": getattr(settings, "ALLOW_SIGNUPS", False),
        },
    )


@login_required
def user_create(request):
    _require_superuser(request)
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            _record_user_audit(
                action=AuditLog.Action.CREATE,
                target=user,
                actor=request.user,
                changes={
                    "created": {
                        "user_id": user.pk,
                        "username": user.get_username(),
                        "is_active": user.is_active,
                        "source": "superuser",
                    }
                },
            )
        messages.success(request, f"Account {user.get_username()} was created.")
        return redirect("tracker:user_list")
    return render(
        request,
        "tracker/user_form.html",
        {
            "form": form,
            "title": "Create user",
            "submit_label": "Create user",
        },
    )


@require_POST
@login_required
def user_deactivate(request, user_id):
    _require_superuser(request)
    User = get_user_model()
    with transaction.atomic():
        target = get_object_or_404(
            User._default_manager.select_for_update(),
            pk=user_id,
        )
        if target.pk == request.user.pk:
            messages.error(request, "You cannot deactivate your own account.")
        elif not target.is_active:
            _revoke_user_sessions(target.pk)
            messages.info(request, f"{target.get_username()} is already inactive.")
        else:
            active_superuser_ids = list(
                User._default_manager.select_for_update()
                .filter(is_active=True, is_superuser=True)
                .values_list("pk", flat=True)
            )
            if target.is_superuser and len(active_superuser_ids) <= 1:
                messages.error(
                    request,
                    "The last active superuser cannot be deactivated.",
                )
            else:
                target.is_active = False
                target.save(update_fields=["is_active"])
                revoked_sessions = _revoke_user_sessions(target.pk)
                _record_user_audit(
                    action=AuditLog.Action.UPDATE,
                    target=target,
                    actor=request.user,
                    changes={
                        "user_id": target.pk,
                        "is_active": {"before": True, "after": False},
                        "sessions_revoked": revoked_sessions,
                    },
                )
                messages.success(
                    request,
                    f"{target.get_username()} was deactivated. Their batch data was preserved.",
                )
    return redirect("tracker:user_list")


@require_POST
@login_required
def user_reactivate(request, user_id):
    _require_superuser(request)
    User = get_user_model()
    with transaction.atomic():
        target = get_object_or_404(
            User._default_manager.select_for_update(),
            pk=user_id,
        )
        if target.is_active:
            messages.info(request, f"{target.get_username()} is already active.")
        else:
            target.is_active = True
            target.save(update_fields=["is_active"])
            _record_user_audit(
                action=AuditLog.Action.UPDATE,
                target=target,
                actor=request.user,
                changes={
                    "user_id": target.pk,
                    "is_active": {"before": False, "after": True},
                },
            )
            messages.success(request, f"{target.get_username()} was reactivated.")
    return redirect("tracker:user_list")


def _owned_batch(user, pk, *, include_deleted: bool = False) -> Batch:
    manager = Batch.all_objects if include_deleted else Batch.objects
    return get_object_or_404(manager, pk=pk, owner=user)


def _owned_entry(user, kind: str, pk, *, include_deleted: bool = False):
    try:
        model, form_class, label_text = ENTRY_TYPES[kind]
    except KeyError as exc:
        raise Http404("Unknown entry type.") from exc
    manager = model.all_objects if include_deleted else model.objects
    entry = get_object_or_404(
        manager.select_related("batch"),
        pk=pk,
        batch__owner=user,
    )
    return entry, form_class, label_text


def _active_qr_link(batch: Batch, user) -> QRLink:
    qr_link = batch.qr_links.filter(is_active=True).first()
    if qr_link is None:
        qr_link = QRLink.objects.create(batch=batch, created_by=user)
    return qr_link


def _qr_target_url(request, qr_link: QRLink) -> str:
    path = reverse("tracker:qr_batch", kwargs={"token": qr_link.token})
    if settings.PUBLIC_BASE_URL:
        return f"{settings.PUBLIC_BASE_URL}{path}"
    return request.build_absolute_uri(path)


def _base_url_warning(qr_url: str) -> str:
    parsed = urlparse(qr_url)
    if not settings.PUBLIC_BASE_URL:
        return (
            "No public base URL is configured. This preview uses the current "
            "browser address, which may not be reachable from your phone."
        )
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return (
            "The configured QR address points to this computer only. Set "
            "MEAD_TRACKER_PUBLIC_BASE_URL to a stable address your phone can reach "
            "before printing bottle labels."
        )
    return ""


LABEL_BORDER_COLOR_VALUES = {
    LabelSizeForm.BORDER_AMBER: "#9b5a1a",
    LabelSizeForm.BORDER_FOREST: "#315e45",
    LabelSizeForm.BORDER_BURGUNDY: "#7a3040",
    LabelSizeForm.BORDER_NAVY: "#334e68",
    LabelSizeForm.BORDER_CHARCOAL: "#3f4642",
}


def _label_preview_context(form: LabelSizeForm) -> dict:
    values = {
        "preset": LabelSizeForm.PRESET_3_X_4,
        "width": LabelSizeForm.PRESET_DIMENSIONS[
            LabelSizeForm.PRESET_3_X_4
        ][0],
        "height": LabelSizeForm.PRESET_DIMENSIONS[
            LabelSizeForm.PRESET_3_X_4
        ][1],
        "dimension_unit": LabelPrintLog.DimensionUnit.INCH,
        "border_style": LabelSizeForm.BORDER_CLASSIC,
        "border_color": LabelSizeForm.BORDER_AMBER,
    }
    if form.is_bound and not form.errors:
        values.update(form.cleaned_data)

    width = values["width"]
    height = values["height"]
    preset = values["preset"]
    border_color = values["border_color"]
    return {
        "label_width": width,
        "label_height": height,
        "label_aspect_ratio": float(width / height),
        "label_orientation": "landscape" if width > height else "portrait",
        "label_is_avery_94051": (
            preset == LabelSizeForm.PRESET_AVERY_PRESTA_94051
        ),
        "label_border_style": values["border_style"],
        "label_border_color": border_color,
        "label_border_color_value": LABEL_BORDER_COLOR_VALUES.get(
            border_color,
            LABEL_BORDER_COLOR_VALUES[LabelSizeForm.BORDER_AMBER],
        ),
        "label_dimension_unit": values["dimension_unit"],
    }


def _batch_context(batch: Batch) -> dict:
    active_additions = list(
        batch.additions.order_by("added_at", "recorded_at")
    )
    visual_mark = build_visual_mark(batch, additions=active_additions)
    batch.visual_mark = visual_mark
    gravity = build_gravity_summary(batch)
    stage_visual = build_stage_visual(
        batch,
        additions=active_additions,
        gravity_readings=gravity["readings"],
        status_history=batch.status_history.all(),
    )
    batch.stage_visual = stage_visual
    all_activity = build_activity(batch, include_deleted=True)
    estimated_abv = (
        gravity["final_abv"]
        if gravity["final_abv"] is not None
        else gravity["live_abv"]
    )
    return {
        "batch": batch,
        "visual_mark": visual_mark,
        "stage_visual": stage_visual,
        "activity": build_activity(batch, additions=active_additions),
        "additions": active_additions,
        "gravity_readings": gravity["readings"],
        "observations": batch.observations.order_by("-observed_at"),
        "latest_gravity": gravity["latest"],
        "original_gravity": gravity["original"],
        "final_gravity": gravity["final"],
        "estimated_abv": estimated_abv,
        "estimated_abv_is_final": bool(gravity["final_abv"] is not None),
        "chart": gravity["chart"],
        "deleted_entries": [entry for entry in all_activity if entry["deleted"]],
        "audit_logs": batch.audit_logs.select_related("actor")[:25],
        "display_timezone": settings.TIME_ZONE,
    }


@login_required
def dashboard(request):
    batches = Batch.objects.filter(owner=request.user).prefetch_related(
        Prefetch(
            "additions",
            queryset=Addition.objects.order_by("added_at", "recorded_at"),
        ),
        Prefetch(
            "gravity_readings",
            queryset=GravityReading.objects.order_by(
                "measured_at",
                "recorded_at",
            ),
        ),
        Prefetch(
            "observations",
            queryset=Observation.objects.order_by(
                "observed_at",
                "recorded_at",
            ),
        ),
        Prefetch(
            "status_history",
            queryset=BatchStatusHistory.objects.order_by(
                "changed_at",
                "recorded_at",
            ),
        ),
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        batches = batches.filter(
            Q(name__icontains=query)
            | Q(batch_number__icontains=query)
            | Q(style__icontains=query)
        )
    if status in Batch.Status.values:
        batches = batches.filter(status=status)

    batch_cards = []
    recent_activity = []
    for batch in batches:
        active_additions = list(batch.additions.all())
        gravity_readings = list(batch.gravity_readings.all())
        observations = list(batch.observations.all())
        status_history = list(batch.status_history.all())
        batch.visual_mark = build_visual_mark(
            batch,
            additions=active_additions,
        )
        batch.stage_visual = build_stage_visual(
            batch,
            additions=active_additions,
            gravity_readings=gravity_readings,
            status_history=status_history,
        )
        batch_cards.append(batch)
        recent_activity.extend(
            build_activity(
                batch,
                additions=active_additions,
                gravity_readings=gravity_readings,
                observations=observations,
                status_history=status_history,
            )[:5]
        )
    recent_activity.sort(key=lambda item: item["timestamp"], reverse=True)
    active_statuses = {
        Batch.Status.PLANNING,
        Batch.Status.FERMENTING,
        Batch.Status.CONDITIONING,
        Batch.Status.AGING,
    }
    return render(
        request,
        "tracker/dashboard.html",
        {
            "batches": batch_cards,
            "batch_cards": batch_cards,
            "activity": recent_activity[:8],
            "active_count": sum(
                1 for batch in batch_cards if batch.status in active_statuses
            ),
            "fermenting_count": sum(
                1
                for batch in batch_cards
                if batch.status == Batch.Status.FERMENTING
            ),
            "bottled_count": sum(
                1 for batch in batch_cards if batch.status == Batch.Status.BOTTLED
            ),
            "query": query,
            "selected_status": status,
            "status_choices": Batch.Status.choices,
        },
    )


@login_required
def batch_create(request):
    form = BatchForm(request.POST or None, owner=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            batch = form.save()
            BatchStatusHistory.objects.create(
                batch=batch,
                status=batch.status,
                changed_at=timezone.now(),
                notes="Batch created.",
                changed_by=request.user,
            )
            QRLink.objects.create(batch=batch, created_by=request.user)
            record_audit(
                action=AuditLog.Action.CREATE,
                instance=batch,
                actor=request.user,
                changes={"created": snapshot(batch)},
            )
        messages.success(request, f"{batch.name} was created.")
        return redirect("tracker:batch_detail", pk=batch.pk)
    return render(
        request,
        "tracker/batch_form.html",
        {"form": form, "title": "Start a mead batch", "submit_label": "Create batch"},
    )


@login_required
def batch_detail(request, pk):
    batch = _owned_batch(request.user, pk)
    return render(request, "tracker/batch_detail.html", _batch_context(batch))


@login_required
def batch_edit(request, pk):
    batch = _owned_batch(request.user, pk)
    before = snapshot(batch)
    form = BatchForm(request.POST or None, instance=batch, owner=request.user)
    if request.method == "POST" and form.is_valid():
        batch = form.save()
        record_audit(
            action=AuditLog.Action.UPDATE,
            instance=batch,
            actor=request.user,
            changes=changes_between(before, snapshot(batch)),
        )
        messages.success(request, "Batch details updated.")
        return redirect("tracker:batch_detail", pk=batch.pk)
    return render(
        request,
        "tracker/batch_form.html",
        {
            "form": form,
            "batch": batch,
            "title": f"Edit {batch.name}",
            "submit_label": "Save changes",
        },
    )


def _event_form(
    request,
    *,
    batch: Batch,
    form_class,
    kind: str,
    instance=None,
    template_name: str = "tracker/event_form.html",
):
    before = snapshot(instance) if instance is not None else {}
    form = form_class(
        request.POST or None,
        request.FILES or None,
        instance=instance,
    )
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.batch = batch
        entry.recorded_by = request.user

        if isinstance(entry, GravityReading) and entry.reading_type in {
            GravityReading.ReadingType.ORIGINAL,
            GravityReading.ReadingType.FINAL,
        }:
            existing = batch.gravity_readings.filter(
                reading_type=entry.reading_type
            ).exclude(pk=entry.pk)
            if existing.exists():
                form.add_error(
                    "reading_type",
                    f"This batch already has a {entry.get_reading_type_display()}. "
                    "Edit that reading or mark this one as routine.",
                )
            else:
                try:
                    with transaction.atomic():
                        entry.save()
                except IntegrityError:
                    form.add_error(
                        "reading_type",
                        "Another reading already has this role. Refresh the page "
                        "and edit the existing OG or FG reading.",
                    )
        else:
            entry.save()

        if not form.errors:
            action = (
                AuditLog.Action.UPDATE if instance is not None else AuditLog.Action.CREATE
            )
            changes = (
                changes_between(before, snapshot(entry))
                if instance is not None
                else {"created": snapshot(entry)}
            )
            record_audit(
                action=action,
                instance=entry,
                actor=request.user,
                changes=changes,
            )
            messages.success(
                request,
                f"{kind.capitalize()} {'updated' if instance else 'recorded'}.",
            )
            return redirect("tracker:batch_detail", pk=batch.pk)

    return render(
        request,
        template_name,
        {
            "batch": batch,
            "form": form,
            "kind": kind,
            "title": f"{'Edit' if instance else 'Add'} {kind}",
            "submit_label": "Save update",
            "entry": instance,
        },
    )


@login_required
def addition_add(request, batch_pk):
    return _event_form(
        request,
        batch=_owned_batch(request.user, batch_pk),
        form_class=AdditionForm,
        kind="ingredient addition",
        template_name="tracker/addition_form.html",
    )


@login_required
def addition_edit(request, pk):
    entry, _, _ = _owned_entry(request.user, "addition", pk)
    batch = entry.batch
    return _event_form(
        request,
        batch=batch,
        form_class=AdditionForm,
        kind="ingredient addition",
        instance=entry,
        template_name="tracker/addition_form.html",
    )


@login_required
def gravity_add(request, batch_pk):
    return _event_form(
        request,
        batch=_owned_batch(request.user, batch_pk),
        form_class=GravityReadingForm,
        kind="gravity reading",
        template_name="tracker/gravity_form.html",
    )


@login_required
def gravity_edit(request, pk):
    entry, _, _ = _owned_entry(request.user, "gravity", pk)
    batch = entry.batch
    return _event_form(
        request,
        batch=batch,
        form_class=GravityReadingForm,
        kind="gravity reading",
        instance=entry,
        template_name="tracker/gravity_form.html",
    )


@login_required
def observation_add(request, batch_pk):
    return _event_form(
        request,
        batch=_owned_batch(request.user, batch_pk),
        form_class=ObservationForm,
        kind="observation",
        template_name="tracker/observation_form.html",
    )


@login_required
def observation_edit(request, pk):
    entry, _, _ = _owned_entry(request.user, "observation", pk)
    batch = entry.batch
    return _event_form(
        request,
        batch=batch,
        form_class=ObservationForm,
        kind="observation",
        instance=entry,
        template_name="tracker/observation_form.html",
    )


@login_required
def observation_photo(request, pk):
    observation, _, _ = _owned_entry(request.user, "observation", pk)
    if not observation.photo:
        raise Http404("This observation does not have a photo.")

    try:
        photo_file = observation.photo.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("The observation photo could not be found.") from exc

    content_type, _ = mimetypes.guess_type(observation.photo.name)
    response = FileResponse(
        photo_file,
        content_type=content_type or "application/octet-stream",
    )
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
def status_update(request, batch_pk):
    batch = _owned_batch(request.user, batch_pk)
    old_status = batch.status
    form = BatchStatusForm(request.POST or None, batch=batch)
    if request.method == "POST" and form.is_valid():
        history = form.save(changed_by=request.user)
        record_audit(
            action=AuditLog.Action.STATUS,
            instance=batch,
            actor=request.user,
            changes={
                "status": {
                    "before": old_status,
                    "after": batch.status,
                },
                "recorded_history": {
                    "status": history.status,
                    "changed_at": history.changed_at.isoformat(),
                    "notes": history.notes,
                },
            },
        )
        if old_status == history.status and batch.status == history.status:
            messages.success(
                request,
                f"{history.get_status_display()} timing recorded.",
            )
        elif batch.status == history.status:
            messages.success(
                request,
                f"Status changed to {history.get_status_display()}.",
            )
        else:
            messages.success(
                request,
                "Historical status recorded; the batch's current status was left unchanged.",
            )
        return redirect("tracker:batch_detail", pk=batch.pk)
    return render(
        request,
        "tracker/status_form.html",
        {
            "batch": batch,
            "form": form,
            "kind": "status",
            "title": f"Update {batch.name}'s status",
            "submit_label": "Update status",
        },
    )


@login_required
def entry_delete(request, kind, pk):
    entry, _, label_text = _owned_entry(request.user, kind, pk)
    form = ConfirmDeleteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        before = snapshot(entry)
        entry.delete()
        record_audit(
            action=AuditLog.Action.DELETE,
            instance=entry,
            actor=request.user,
            changes={"deleted": before},
        )
        messages.success(request, f"The {label_text} was moved to recently removed.")
        return redirect("tracker:batch_detail", pk=entry.batch_id)
    return render(
        request,
        "tracker/confirm_delete.html",
        {
            "batch": entry.batch,
            "entry": entry,
            "object": entry,
            "kind": kind,
            "label": label_text,
            "form": form,
        },
    )


@require_POST
@login_required
def entry_restore(request, kind, pk):
    entry, _, label_text = _owned_entry(
        request.user,
        kind,
        pk,
        include_deleted=True,
    )
    if entry.deleted_at is None:
        messages.info(request, f"That {label_text} is already active.")
    elif (
        isinstance(entry, GravityReading)
        and entry.reading_type
        in {
            GravityReading.ReadingType.ORIGINAL,
            GravityReading.ReadingType.FINAL,
        }
        and entry.batch.gravity_readings.filter(
            reading_type=entry.reading_type
        ).exists()
    ):
        messages.error(
            request,
            "This batch already has an active reading with that OG/FG role. "
            "Change the active reading to Routine before restoring this one.",
        )
    else:
        try:
            with transaction.atomic():
                entry.restore()
                record_audit(
                    action=AuditLog.Action.RESTORE,
                    instance=entry,
                    actor=request.user,
                    changes={"restored": snapshot(entry)},
                )
        except IntegrityError:
            messages.error(
                request,
                "That record conflicts with an active batch record and could not "
                "be restored.",
            )
        else:
            messages.success(request, f"The {label_text} was restored.")
    return redirect("tracker:batch_detail", pk=entry.batch_id)


@login_required
def label(request, pk):
    batch = _owned_batch(request.user, pk)
    qr_link = _active_qr_link(batch, request.user)
    qr_url = _qr_target_url(request, qr_link)
    form = LabelSizeForm(request.GET or None)
    if request.GET:
        form.is_valid()
    return render(
        request,
        "tracker/label.html",
        {
            "batch": batch,
            "form": form,
            "label_form": form,
            "qr_url": qr_url,
            "base_url_warning": _base_url_warning(qr_url),
            **_label_preview_context(form),
        },
    )


@login_required
def qr_svg(request, pk):
    batch = _owned_batch(request.user, pk)
    qr_link = _active_qr_link(batch, request.user)
    qr_url = _qr_target_url(request, qr_link)
    stream = BytesIO()
    segno.make(qr_url, error="q", micro=False).save(
        stream,
        kind="svg",
        scale=7,
        border=4,
        dark="#17261e",
        light="#ffffff",
        xmldecl=False,
    )
    return HttpResponse(
        stream.getvalue(),
        content_type="image/svg+xml; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300"},
    )


@login_required
def label_pdf(request, pk):
    batch = _owned_batch(request.user, pk)
    form_data = request.GET or {
        "preset": LabelSizeForm.PRESET_3_X_4,
        "dimension_unit": LabelPrintLog.DimensionUnit.INCH,
        "output_mode": LabelPrintLog.OutputMode.SINGLE,
        "copies": "1",
        "include_batch_number": "on",
    }
    form = LabelSizeForm(form_data)
    qr_link = _active_qr_link(batch, request.user)
    qr_url = _qr_target_url(request, qr_link)
    if not form.is_valid():
        return render(
            request,
            "tracker/label.html",
            {
                "batch": batch,
                "form": form,
                "label_form": form,
                "qr_url": qr_url,
                "base_url_warning": _base_url_warning(qr_url),
                **_label_preview_context(form),
            },
            status=400,
        )

    values = form.cleaned_data
    pdf = render_label_pdf(
        batch=batch,
        qr_url=qr_url,
        width=values["width"],
        height=values["height"],
        dimension_unit=values["dimension_unit"],
        copies=values["copies"],
        output_mode=values["output_mode"],
        include_batch_number=values["include_batch_number"],
        label_preset=values["preset"],
        border_style=values["border_style"],
        border_color=values["border_color"],
    )
    LabelPrintLog.objects.create(
        batch=batch,
        qr_link=qr_link,
        printed_by=request.user,
        label_preset=values["preset"],
        width=values["width"],
        height=values["height"],
        dimension_unit=values["dimension_unit"],
        output_mode=values["output_mode"],
        copies=values["copies"],
    )
    safe_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in batch.name.lower()
    ).strip("-")
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{safe_name or "mead"}-label.pdf"'
    )
    return response


@login_required
def qr_batch(request, token):
    qr_link = get_object_or_404(
        QRLink.objects.select_related("batch", "batch__owner"),
        token=token,
        is_active=True,
        batch__deleted_at__isnull=True,
    )
    if qr_link.batch.owner_id != request.user.id:
        raise Http404("QR link not found.")
    QRLink.objects.filter(pk=qr_link.pk).update(
        last_scanned_at=timezone.now(),
        scan_count=F("scan_count") + 1,
    )
    context = _batch_context(qr_link.batch)
    context.update({"qr_link": qr_link, "mobile_quick_entry": True})
    return render(request, "tracker/mobile_batch.html", context)


@login_required
def batch_trash(request, pk):
    batch = _owned_batch(request.user, pk)
    deleted_entries = [
        entry for entry in build_activity(batch, include_deleted=True) if entry["deleted"]
    ]
    return render(
        request,
        "tracker/trash.html",
        {"batch": batch, "deleted_entries": deleted_entries},
    )


@login_required
def batch_export(request, pk):
    try:
        payload = get_owned_batch_context(owner=request.user, batch_id=pk)
    except Batch.DoesNotExist as exc:
        raise Http404("Batch not found.") from exc
    contents = json.dumps(payload, cls=DjangoJSONEncoder, indent=2)
    response = HttpResponse(contents, content_type="application/json")
    response["Content-Disposition"] = (
        f'attachment; filename="mead-batch-{pk}.json"'
    )
    return response


@login_required
def database_backup(request):
    if not request.user.is_staff:
        raise PermissionDenied("Only an owner/administrator can download a full backup.")
    try:
        contents, filename = create_backup_bytes()
    except BackupError as exc:
        messages.error(request, str(exc))
        return redirect("tracker:dashboard")
    response = HttpResponse(contents, content_type="application/vnd.sqlite3")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def help_page(request):
    return render(request, "tracker/help.html")
