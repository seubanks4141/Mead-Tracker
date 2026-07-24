from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.http import HttpResponse
from django.test import (
    RequestFactory,
    TestCase,
    override_settings,
)
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tracker.forms import BatchForm
from tracker.models import (
    Addition,
    Batch,
    BatchStatusHistory,
    GravityReading,
    QRLink,
)
from tracker.services.stages import build_stage_visual
from tracker.views import dashboard


UTC = ZoneInfo("UTC")
CHICAGO = ZoneInfo("America/Chicago")


class StageVisualServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="stage-owner",
            password="Stage-Honey-42!",
        )

    def setUp(self):
        self.as_of = datetime(2026, 7, 24, 18, 0, tzinfo=UTC)
        self.started_at = self.as_of - timedelta(days=8)

    def make_batch(self, **overrides):
        values = {
            "owner": self.user,
            "name": "Stage test mead",
            "start_date": self.started_at.date(),
            "status": Batch.Status.FERMENTING,
            "fermentation_started_at": self.started_at,
            "target_fermentation_sg": Decimal("1.0100"),
        }
        values.update(overrides)
        batch = Batch.objects.create(**values)
        BatchStatusHistory.objects.create(
            batch=batch,
            status=batch.status,
            changed_at=self.started_at,
        )
        return batch

    def add_reading(
        self,
        batch,
        sg,
        when,
        *,
        reading_type=GravityReading.ReadingType.ROUTINE,
        method=GravityReading.Method.HYDROMETER,
    ):
        return GravityReading.objects.create(
            batch=batch,
            specific_gravity=Decimal(sg),
            reading_type=reading_type,
            method=method,
            measured_at=when,
        )

    def prompt_codes(self, visual):
        return {prompt["code"] for prompt in visual["prompts"]}

    def test_contract_and_gravity_progress_are_bounded(self):
        batch = self.make_batch()
        self.add_reading(
            batch,
            "1.1000",
            self.started_at - timedelta(hours=1),
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        self.add_reading(batch, "1.0550", self.started_at + timedelta(days=4))

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertEqual(
            set(visual),
            {
                "status",
                "stage_label",
                "entered_at",
                "elapsed_days",
                "elapsed_label",
                "ring_mode",
                "progress",
                "summary",
                "accessible_summary",
                "basis",
                "basis_code",
                "confidence",
                "forecast_label",
                "details",
                "prompts",
                "original_sg",
                "latest_sg",
                "target_sg",
            },
        )
        self.assertEqual(visual["ring_mode"], "gravity")
        self.assertEqual(visual["progress"], 50)
        self.assertEqual(visual["confidence"], "limited")
        self.assertTrue(0 <= visual["progress"] <= 100)
        self.assertTrue(
            all(set(prompt) == {"code", "message"} for prompt in visual["prompts"])
        )

    def test_three_recent_downward_readings_add_only_a_cautious_forecast(self):
        batch = self.make_batch()
        self.add_reading(
            batch,
            "1.1000",
            self.started_at - timedelta(hours=1),
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        for days, sg in ((2, "1.0800"), (4, "1.0650"), (6, "1.0520")):
            self.add_reading(batch, sg, self.started_at + timedelta(days=days))

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertEqual(visual["ring_mode"], "gravity")
        self.assertEqual(visual["confidence"], "trend")
        self.assertIn("roughly", visual["forecast_label"].lower())
        self.assertNotIn("complete", visual["forecast_label"].lower())
        self.assertNotIn("bottle", visual["forecast_label"].lower())
        self.assertEqual(batch.status, Batch.Status.FERMENTING)

    def test_latest_flat_or_rebounding_pair_suppresses_forecast(self):
        for suffix, readings in (
            ("flat", ("1.0600", "1.0500", "1.0500")),
            ("rebound", ("1.0600", "1.0480", "1.0520")),
        ):
            with self.subTest(suffix=suffix):
                batch = self.make_batch(name=f"Trend {suffix}")
                self.add_reading(
                    batch,
                    "1.1000",
                    self.started_at - timedelta(hours=1),
                    reading_type=GravityReading.ReadingType.ORIGINAL,
                )
                for days, sg in zip((2, 4, 6), readings):
                    self.add_reading(
                        batch,
                        sg,
                        self.started_at + timedelta(days=days),
                    )

                visual = build_stage_visual(batch, as_of=self.as_of)

                self.assertEqual(visual["ring_mode"], "gravity")
                self.assertEqual(visual["forecast_label"], "")
                self.assertEqual(visual["confidence"], "limited")

    def test_accelerating_trend_can_forecast_but_slowing_trend_is_cautious(self):
        accelerating = self.make_batch(name="Accelerating trend")
        self.add_reading(
            accelerating,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        for days, sg in ((1, "1.0900"), (2, "1.0750"), (3, "1.0500")):
            self.add_reading(
                accelerating,
                sg,
                self.started_at + timedelta(days=days),
            )
        accelerating_visual = build_stage_visual(
            accelerating,
            as_of=self.started_at + timedelta(days=4),
        )
        self.assertTrue(accelerating_visual["forecast_label"])

        slowing = self.make_batch(name="Strongly slowing trend")
        self.add_reading(
            slowing,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        for days, sg in ((1, "1.0500"), (2, "1.0400"), (3, "1.0398")):
            self.add_reading(
                slowing,
                sg,
                self.started_at + timedelta(days=days),
            )
        slowing_visual = build_stage_visual(
            slowing,
            as_of=self.started_at + timedelta(days=4),
        )
        self.assertEqual(slowing_visual["forecast_label"], "")
        self.assertEqual(slowing_visual["confidence"], "limited")

    def test_kinetics_changing_additions_reset_forecast_not_progress(self):
        for kind in (
            Addition.Kind.NUTRIENT,
            Addition.Kind.YEAST,
            Addition.Kind.STABILIZER,
        ):
            with self.subTest(kind=kind):
                batch = self.make_batch(name=f"Forecast reset {kind}")
                self.add_reading(
                    batch,
                    "1.1000",
                    self.started_at,
                    reading_type=GravityReading.ReadingType.ORIGINAL,
                )
                for days, sg in ((1, "1.0900"), (2, "1.0800"), (3, "1.0700")):
                    self.add_reading(
                        batch,
                        sg,
                        self.started_at + timedelta(days=days),
                    )
                Addition.objects.create(
                    batch=batch,
                    kind=kind,
                    name=f"{kind} intervention",
                    quantity="1",
                    unit="g",
                    added_at=self.started_at + timedelta(days=4),
                )
                for days, sg in ((5, "1.0600"), (6, "1.0520")):
                    self.add_reading(
                        batch,
                        sg,
                        self.started_at + timedelta(days=days),
                    )

                two_after = build_stage_visual(batch, as_of=self.as_of)
                self.assertEqual(two_after["ring_mode"], "gravity")
                self.assertEqual(two_after["forecast_label"], "")

                self.add_reading(
                    batch,
                    "1.0450",
                    self.started_at + timedelta(days=7),
                )
                three_after = build_stage_visual(batch, as_of=self.as_of)
                self.assertTrue(three_after["forecast_label"])
                self.assertEqual(three_after["confidence"], "trend")

    def test_unobserved_gap_is_not_subtracted_from_remaining_forecast(self):
        batch = self.make_batch(name="Unobserved gap")
        self.add_reading(
            batch,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        self.add_reading(
            batch,
            "1.0900",
            self.started_at + timedelta(days=1),
        )
        self.add_reading(
            batch,
            "1.0800",
            self.started_at + timedelta(days=2),
        )
        self.add_reading(
            batch,
            "1.0700",
            self.started_at + timedelta(days=3),
        )

        visual_at_latest_sample = build_stage_visual(
            batch,
            as_of=self.started_at + timedelta(days=3),
        )
        visual_after_gap = build_stage_visual(
            batch,
            as_of=self.started_at + timedelta(days=9),
        )

        self.assertIn("4\u20139 days", visual_after_gap["forecast_label"])
        self.assertEqual(
            visual_after_gap["forecast_label"],
            visual_at_latest_sample["forecast_label"],
        )

    def test_post_pitch_refractometer_is_not_used_for_progress(self):
        batch = self.make_batch()
        self.add_reading(
            batch,
            "1.1000",
            self.started_at - timedelta(hours=1),
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        self.add_reading(
            batch,
            "1.0450",
            self.started_at + timedelta(days=5),
            method=GravityReading.Method.REFRACTOMETER,
        )

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertEqual(visual["ring_mode"], "unknown")
        self.assertIsNone(visual["progress"])
        self.assertIn("add_reading", self.prompt_codes(visual))
        self.assertTrue(
            any("refractometer" in detail.lower() for detail in visual["details"])
        )

    def test_original_refractometer_after_start_is_not_a_usable_og(self):
        batch = self.make_batch()
        self.add_reading(
            batch,
            "1.1000",
            self.started_at + timedelta(hours=1),
            reading_type=GravityReading.ReadingType.ORIGINAL,
            method=GravityReading.Method.REFRACTOMETER,
        )
        self.add_reading(batch, "1.0500", self.started_at + timedelta(days=4))

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertIsNone(visual["original_sg"])
        self.assertEqual(visual["ring_mode"], "unknown")
        self.assertIn("add_original", self.prompt_codes(visual))

    def test_recipe_changing_addition_requires_new_baseline_and_later_reading(self):
        batch = self.make_batch()
        self.add_reading(
            batch,
            "1.1000",
            self.started_at - timedelta(hours=1),
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        addition_time = self.started_at + timedelta(days=3)
        Addition.objects.create(
            batch=batch,
            kind=Addition.Kind.HONEY,
            name="Backsweetening honey",
            quantity="1",
            unit="lb",
            added_at=addition_time,
        )
        self.add_reading(batch, "1.0700", addition_time)

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertEqual(visual["basis_code"], "addition_reset")
        self.assertEqual(visual["ring_mode"], "unknown")
        self.assertIn("add_reading", self.prompt_codes(visual))

    def test_deleted_reading_and_addition_are_ignored_even_when_passed(self):
        batch = self.make_batch()
        self.add_reading(
            batch,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        self.add_reading(batch, "1.0550", self.started_at + timedelta(days=4))
        removed_addition = Addition.objects.create(
            batch=batch,
            kind=Addition.Kind.HONEY,
            name="Removed honey",
            quantity="1",
            unit="lb",
            added_at=self.started_at + timedelta(days=5),
        )
        removed_addition.delete()
        removed_reading = self.add_reading(
            batch,
            "1.5000",
            self.started_at + timedelta(days=6),
        )
        removed_reading.delete()

        visual = build_stage_visual(
            batch,
            additions=Addition.all_objects.filter(batch=batch),
            gravity_readings=GravityReading.all_objects.filter(batch=batch),
            status_history=batch.status_history.all(),
            as_of=self.as_of,
        )

        self.assertEqual(visual["ring_mode"], "gravity")
        self.assertEqual(visual["progress"], 50)
        self.assertEqual(visual["latest_sg"], Decimal("1.0550"))

    def test_invalid_target_direction_and_implausible_sg_are_unknown(self):
        cases = (
            ("target above OG", "1.1000", "1.1200", "1.0500"),
            ("target out of range", "1.1000", "0.8000", "1.0500"),
            ("implausible OG", "1.7000", "1.0100", "1.0500"),
            ("implausible latest", "1.1000", "1.0100", "1.7000"),
        )
        for name, original_sg, target_sg, latest_sg in cases:
            with self.subTest(name=name):
                batch = self.make_batch(
                    name=name,
                    target_fermentation_sg=Decimal(target_sg),
                )
                self.add_reading(
                    batch,
                    original_sg,
                    self.started_at,
                    reading_type=GravityReading.ReadingType.ORIGINAL,
                )
                self.add_reading(
                    batch,
                    latest_sg,
                    self.started_at + timedelta(days=4),
                )

                visual = build_stage_visual(batch, as_of=self.as_of)

                self.assertEqual(visual["ring_mode"], "unknown")
                self.assertIsNone(visual["progress"])

    def test_latest_usable_sg_is_shown_when_an_input_is_missing(self):
        cases = (
            ("missing target", "1.1000", None),
            ("invalid original", "1.7000", Decimal("1.0100")),
        )
        for name, original_sg, target_sg in cases:
            with self.subTest(name=name):
                batch = self.make_batch(
                    name=name,
                    target_fermentation_sg=target_sg,
                )
                self.add_reading(
                    batch,
                    original_sg,
                    self.started_at,
                    reading_type=GravityReading.ReadingType.ORIGINAL,
                )
                self.add_reading(
                    batch,
                    "1.0550",
                    self.started_at + timedelta(days=4),
                )

                visual = build_stage_visual(batch, as_of=self.as_of)

                self.assertEqual(visual["ring_mode"], "unknown")
                self.assertEqual(visual["latest_sg"], Decimal("1.0550"))

    def test_future_and_duplicate_readings_do_not_drive_estimates(self):
        future_batch = self.make_batch(name="Future reading")
        self.add_reading(
            future_batch,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        self.add_reading(
            future_batch,
            "1.0200",
            self.as_of + timedelta(days=1),
        )
        future_visual = build_stage_visual(
            future_batch,
            as_of=self.as_of,
        )
        self.assertEqual(future_visual["ring_mode"], "unknown")
        self.assertTrue(
            any("future-dated" in detail.lower() for detail in future_visual["details"])
        )

        duplicate_batch = self.make_batch(name="Duplicate times")
        self.add_reading(
            duplicate_batch,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        duplicate_time = self.started_at + timedelta(days=3)
        self.add_reading(duplicate_batch, "1.0600", duplicate_time)
        self.add_reading(
            duplicate_batch,
            "1.0550",
            duplicate_time,
            method=GravityReading.Method.DIGITAL,
        )
        duplicate_visual = build_stage_visual(
            duplicate_batch,
            as_of=self.as_of,
        )
        self.assertEqual(
            duplicate_visual["basis_code"],
            "duplicate_reading_times",
        )
        self.assertEqual(duplicate_visual["ring_mode"], "unknown")

    def test_future_start_never_produces_negative_or_numeric_progress(self):
        batch = self.make_batch(
            fermentation_started_at=self.as_of + timedelta(days=1),
        )
        self.add_reading(
            batch,
            "1.1000",
            self.started_at,
            reading_type=GravityReading.ReadingType.ORIGINAL,
        )
        self.add_reading(batch, "1.0500", self.started_at + timedelta(days=2))

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertEqual(visual["elapsed_days"], 0)
        self.assertEqual(visual["ring_mode"], "unknown")
        self.assertIsNone(visual["progress"])
        self.assertIn("review_status", self.prompt_codes(visual))

    @override_settings(TIME_ZONE="America/Chicago")
    def test_elapsed_days_use_local_calendar_dates_across_dst(self):
        batch = self.make_batch(
            status=Batch.Status.CONDITIONING,
            fermentation_started_at=None,
            target_fermentation_sg=None,
            planned_conditioning_days=10,
        )
        entered_at = datetime(2026, 3, 7, 12, 0, tzinfo=CHICAGO)
        BatchStatusHistory.objects.filter(batch=batch).update(
            changed_at=entered_at,
        )
        as_of = datetime(2026, 3, 9, 11, 30, tzinfo=CHICAGO)

        visual = build_stage_visual(batch, as_of=as_of)

        self.assertEqual(visual["elapsed_days"], 2)
        self.assertEqual(visual["progress"], 20)

    def test_conditioning_plan_without_stage_start_explains_missing_start(self):
        batch = self.make_batch(
            status=Batch.Status.CONDITIONING,
            fermentation_started_at=None,
            target_fermentation_sg=None,
            planned_conditioning_days=10,
        )
        BatchStatusHistory.objects.filter(batch=batch).delete()

        visual = build_stage_visual(batch, as_of=self.as_of)

        self.assertEqual(visual["basis_code"], "missing_conditioning_start")
        self.assertIsNone(visual["progress"])
        self.assertIn("start time is not recorded", visual["summary"])
        self.assertNotIn("no planned window", visual["summary"])
        self.assertIn("review_status", self.prompt_codes(visual))

    def test_terminal_and_open_ended_stages_do_not_claim_percent_complete(self):
        expected_modes = {
            Batch.Status.PLANNING: "none",
            Batch.Status.AGING: "none",
            Batch.Status.BOTTLED: "complete",
            Batch.Status.COMPLETE: "complete",
        }
        for status, ring_mode in expected_modes.items():
            with self.subTest(status=status):
                batch = self.make_batch(
                    name=f"Stage {status}",
                    status=status,
                    fermentation_started_at=None,
                    target_fermentation_sg=None,
                )
                visual = build_stage_visual(batch, as_of=self.as_of)
                self.assertEqual(visual["ring_mode"], ring_mode)
                self.assertIsNone(visual["progress"])


class StagePlanningFieldTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="legacy-form-owner",
            password="Legacy-Honey-42!",
        )

    def test_legacy_batch_form_post_can_omit_new_optional_fields(self):
        form = BatchForm(
            {
                "name": "Legacy form batch",
                "batch_number": "",
                "style": "",
                "start_date": "2026-07-24",
                "volume": "",
                "volume_unit": "",
                "vessel": "",
                "description": "",
            },
            owner=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())
        batch = form.save()
        self.assertIsNone(batch.fermentation_started_at)
        self.assertIsNone(batch.target_fermentation_sg)
        self.assertIsNone(batch.planned_conditioning_days)

    def test_planned_conditioning_duration_enforces_upper_bound(self):
        batch = Batch(
            owner=self.user,
            name="Invalid plan",
            start_date=timezone.localdate(),
            planned_conditioning_days=3651,
        )
        with self.assertRaises(ValidationError):
            batch.full_clean()


class StageVisualViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="stage-view-owner",
            password="Stage-View-42!",
        )
        cls.batches = []
        now = timezone.now()
        for index in range(3):
            batch = Batch.objects.create(
                owner=cls.user,
                name=f"View stage {index}",
                status=Batch.Status.FERMENTING,
                fermentation_started_at=now - timedelta(days=4),
                target_fermentation_sg=Decimal("1.0100"),
            )
            BatchStatusHistory.objects.create(
                batch=batch,
                status=batch.status,
                changed_at=now - timedelta(days=4),
            )
            GravityReading.objects.create(
                batch=batch,
                specific_gravity=Decimal("1.1000"),
                reading_type=GravityReading.ReadingType.ORIGINAL,
                measured_at=now - timedelta(days=4, hours=1),
            )
            GravityReading.objects.create(
                batch=batch,
                specific_gravity=Decimal("1.0600"),
                measured_at=now - timedelta(days=1),
            )
            cls.batches.append(batch)
        cls.qr_link = QRLink.objects.create(
            batch=cls.batches[0],
            created_by=cls.user,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_attaches_stage_visual_and_prefetches_stage_inputs(self):
        request = RequestFactory().get("/")
        request.user = self.user
        with patch(
            "tracker.views.render",
            side_effect=lambda request, template, context: HttpResponse("ok"),
        ) as mocked_render:
            with CaptureQueriesContext(connection) as queries:
                response = dashboard(request)

        self.assertEqual(response.status_code, 200)
        context = mocked_render.call_args.args[2]
        self.assertTrue(
            all(hasattr(batch, "stage_visual") for batch in context["batches"])
        )
        gravity_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "tracker_gravityreading" in query["sql"].lower()
        ]
        status_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "tracker_batchstatushistory" in query["sql"].lower()
        ]
        self.assertEqual(len(gravity_queries), 1)
        self.assertEqual(len(status_queries), 1)

    def test_detail_and_qr_mobile_context_expose_same_contract(self):
        batch = self.batches[0]
        detail = self.client.get(
            reverse("tracker:batch_detail", args=[batch.pk])
        )
        mobile = self.client.get(
            reverse("tracker:qr_batch", args=[self.qr_link.token])
        )

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(mobile.status_code, 200)
        self.assertEqual(
            detail.context["stage_visual"],
            detail.context["batch"].stage_visual,
        )
        self.assertEqual(
            mobile.context["stage_visual"],
            mobile.context["batch"].stage_visual,
        )

    def test_export_includes_nullable_stage_planning_fields(self):
        batch = self.batches[0]
        response = self.client.get(
            reverse("tracker:batch_export", args=[batch.pk])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        batch_data = payload["batch"]
        self.assertIn("fermentation_started_at", batch_data)
        self.assertEqual(
            batch_data["target_fermentation_sg"],
            "1.0100",
        )
        self.assertIsNone(batch_data["planned_conditioning_days"])
