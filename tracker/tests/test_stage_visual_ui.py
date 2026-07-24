from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tracker.models import Batch, QRLink


def gravity_stage(*, progress=64):
    return {
        "status": "fermenting",
        "stage_label": "Fermenting",
        "entered_at": timezone.now(),
        "elapsed_days": 5,
        "elapsed_label": "5 days in this stage.",
        "ring_mode": "gravity",
        "progress": progress,
        "summary": f"About {progress}% toward the target SG.",
        "accessible_summary": (
            f"Fermenting. About {progress}% toward the target SG. "
            "5 days in this stage."
        ),
        "basis": (
            "Progress uses the usable starting gravity, latest compatible "
            "reading, and target fermentation SG."
        ),
        "confidence": "trend",
        "forecast_label": (
            "Recent gravity readings suggest roughly 2–5 days to the target reading."
        ),
        "details": [
            "Only hydrometer and digital-density readings are used after fermentation begins."
        ],
        "prompts": [
            {
                "code": "add_reading",
                "message": "Keep recording gravity to maintain a useful trend.",
            }
        ],
        "original_sg": "1.1000",
        "latest_sg": "1.0360",
        "target_sg": "1.0000",
    }


class StageVisualRenderedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="stage-ui-owner",
            password="Stage-Visual-42!",
        )
        cls.batch = Batch.objects.create(
            owner=cls.user,
            name="Rendered Stage Mead",
            start_date=date(2026, 7, 1),
            status=Batch.Status.FERMENTING,
        )
        cls.qr_link = QRLink.objects.create(
            batch=cls.batch,
            created_by=cls.user,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def response_with_stage(self, route_name, stage, *args):
        with patch(
            "tracker.views.build_stage_visual",
            return_value=deepcopy(stage),
        ):
            return self.client.get(reverse(route_name, args=args))

    def test_dashboard_renders_stage_mark_summary_and_meter_text(self):
        stage = gravity_stage()
        response = self.response_with_stage("tracker:dashboard", stage)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "batch-mark--ring-gravity")
        self.assertContains(response, "batch-mark--status-fermenting")
        self.assertContains(response, 'role="meter"')
        self.assertContains(response, 'aria-valuenow="64"')
        self.assertContains(response, stage["accessible_summary"])
        self.assertContains(response, stage["summary"])
        self.assertNotContains(response, "batch-mark--age-")
        self.assertNotContains(response, "--age-progress")

    def test_detail_explains_basis_confidence_and_contextual_prompt(self):
        stage = gravity_stage()
        response = self.response_with_stage(
            "tracker:batch_detail",
            stage,
            self.batch.pk,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="stage"')
        self.assertContains(response, "Why this estimate?")
        self.assertContains(response, "Trend-supported")
        self.assertContains(response, "Progress toward target SG")
        self.assertContains(response, stage["basis"])
        self.assertContains(response, stage["forecast_label"])
        self.assertContains(
            response,
            reverse("tracker:gravity_add", args=[self.batch.pk]),
        )
        self.assertContains(
            response,
            "They do not establish that fermentation is finished",
        )

    def test_target_reached_is_not_rendered_as_terminal_completion(self):
        stage = gravity_stage(progress=100)
        stage["summary"] = (
            "At or beyond the target SG. Confirm with stable readings and "
            "your normal process."
        )
        response = self.response_with_stage(
            "tracker:batch_detail",
            stage,
            self.batch.pk,
        )

        self.assertContains(response, "Target SG reached in latest reading")
        self.assertContains(response, "Verify stability")
        self.assertContains(response, "--stage-progress: 96%")
        self.assertContains(
            response,
            "Target specific gravity reached in the latest reading; verify stability",
        )
        self.assertNotContains(response, "batch-mark--ring-complete")
        self.assertNotContains(response, "Status recorded")

    def test_aging_has_no_numeric_meter_or_progress_copy(self):
        stage = gravity_stage()
        stage.update(
            {
                "status": "aging",
                "stage_label": "Aging",
                "ring_mode": "none",
                "progress": None,
                "summary": (
                    "Aging is open-ended. 20 days in this stage. "
                    "No progress ring is shown."
                ),
                "accessible_summary": (
                    "Aging. Open-ended stage; no numeric progress estimate."
                ),
                "confidence": "unavailable",
                "forecast_label": "",
                "prompts": [],
            }
        )
        response = self.response_with_stage(
            "tracker:batch_detail",
            stage,
            self.batch.pk,
        )

        self.assertContains(response, "batch-mark--status-aging")
        self.assertContains(response, "batch-mark--ring-none")
        self.assertNotContains(response, 'role="meter"')
        self.assertNotContains(response, "Approx.")
        self.assertContains(response, "Open-ended stage")

    def test_unknown_planned_and_terminal_modes_keep_distinct_cues(self):
        unknown = gravity_stage()
        unknown.update(
            {
                "ring_mode": "unknown",
                "progress": None,
                "summary": "Progress is unavailable until key gravity inputs are recorded.",
                "accessible_summary": "Fermenting; no numeric estimate is available.",
                "confidence": "unavailable",
                "forecast_label": "",
            }
        )
        unknown_response = self.response_with_stage(
            "tracker:batch_detail",
            unknown,
            self.batch.pk,
        )
        self.assertContains(unknown_response, "batch-mark--ring-unknown")
        self.assertContains(unknown_response, "No numeric estimate")
        self.assertNotContains(unknown_response, 'role="meter"')

        planned = gravity_stage(progress=30)
        planned.update(
            {
                "status": "conditioning",
                "stage_label": "Conditioning",
                "ring_mode": "planned",
                "summary": "Day 3 of your 10-day conditioning plan.",
                "accessible_summary": "Conditioning; day 3 of a planned 10-day window.",
                "forecast_label": "",
                "confidence": "limited",
            }
        )
        planned_response = self.response_with_stage(
            "tracker:batch_detail",
            planned,
            self.batch.pk,
        )
        self.assertContains(planned_response, "batch-mark--ring-planned")
        self.assertContains(planned_response, "Planned window")
        self.assertContains(planned_response, "User-planned")
        self.assertContains(planned_response, 'aria-valuenow="30"')

        complete = gravity_stage()
        complete.update(
            {
                "status": "complete",
                "stage_label": "Complete",
                "ring_mode": "complete",
                "progress": None,
                "summary": "Complete is the status you explicitly recorded.",
                "accessible_summary": "Complete; status explicitly recorded.",
                "confidence": "unavailable",
                "forecast_label": "",
                "prompts": [],
            }
        )
        complete_response = self.response_with_stage(
            "tracker:batch_detail",
            complete,
            self.batch.pk,
        )
        self.assertContains(complete_response, "batch-mark--ring-complete")
        self.assertContains(complete_response, "batch-mark--status-complete")
        self.assertContains(complete_response, "Status recorded")
        self.assertContains(complete_response, "Recorded status")
        self.assertNotContains(complete_response, "Estimate unavailable")
        self.assertContains(complete_response, "Why this stage?")
        self.assertNotContains(complete_response, 'role="meter"')

    def test_mobile_quick_update_reuses_mark_and_concise_summary(self):
        stage = gravity_stage()
        response = self.response_with_stage(
            "tracker:qr_batch",
            stage,
            self.qr_link.token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "batch-mark--compact")
        self.assertContains(response, "mobile-record-stage")
        self.assertContains(response, stage["stage_label"])
        self.assertContains(response, stage["summary"])
        self.assertNotContains(response, "Why this estimate?")

    def test_help_describes_stage_semantics_and_limits(self):
        response = self.client.get(reverse("tracker:help"))

        self.assertContains(response, "The center is its stable recipe identity")
        self.assertContains(response, "There is no outer progress ring")
        self.assertContains(response, "no universal finish line")
        self.assertContains(response, "does not prove fermentation is finished")
        self.assertContains(response, "safe to bottle")
        self.assertNotContains(response, "filled portion shows age through the first year")
        self.assertNotContains(response, "new 30-day age bucket")
