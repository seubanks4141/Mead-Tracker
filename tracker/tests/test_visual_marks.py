from __future__ import annotations

import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tracker.models import Addition, Batch
from tracker.services.presentation import (
    INGREDIENT_KIND_VISUALS,
    VISUAL_MARK_SHAPES,
    build_visual_mark,
)


class VisualMarkServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="visual-owner",
            password="Visual-Honey-42!",
        )
        cls.batch = Batch.objects.create(
            id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            owner=cls.user,
            name="Visual traditional",
            start_date=date(2026, 1, 1),
        )
        Addition.objects.create(
            batch=cls.batch,
            kind=Addition.Kind.HONEY,
            name="Clover honey",
            quantity="10",
            unit="lb",
        )
        Addition.objects.create(
            batch=cls.batch,
            kind=Addition.Kind.FRUIT,
            name="Cherries",
            quantity="2",
            unit="lb",
        )
        removed = Addition.objects.create(
            batch=cls.batch,
            kind=Addition.Kind.SPICE,
            name="Cinnamon",
            quantity="1",
            unit="count",
        )
        removed.delete()

    def test_mark_is_deterministic_safe_and_ignores_deleted_additions(self):
        as_of = date(2026, 7, 24)
        mark = build_visual_mark(self.batch, on_date=as_of)

        self.assertEqual(mark, build_visual_mark(self.batch, on_date=as_of))
        self.assertEqual(mark["ingredient_labels"], ["Fruit", "Honey"])
        self.assertNotIn("Spice or herb", mark["ingredient_labels"])
        self.assertIn(mark["shape"], VISUAL_MARK_SHAPES)
        self.assertTrue(-16 <= mark["rotation"] <= 16)
        self.assertTrue(0.9 <= mark["scale"] <= 1.1)
        self.assertTrue(0 <= mark["age_progress"] <= 100)
        self.assertLessEqual(len(mark["ingredient_markers"]), 4)

        allowed_colors = {
            color
            for visual in INGREDIENT_KIND_VISUALS.values()
            for color in visual["colors"]
        }
        self.assertTrue(set(mark["palette"].values()) <= allowed_colors)
        self.assertIn(mark["color_start"], allowed_colors)
        self.assertIn(mark["color_end"], allowed_colors)
        self.assertIn(mark["glow_color"], allowed_colors)
        self.assertTrue(
            all(
                marker["color"] in allowed_colors
                for marker in mark["ingredient_markers"]
            )
        )

        including_deleted = build_visual_mark(
            self.batch,
            additions=self.batch.additions.model.all_objects.filter(
                batch=self.batch
            ),
            on_date=as_of,
        )
        self.assertEqual(mark, including_deleted)

    def test_uuid_and_age_bucket_contribute_to_identity(self):
        same_recipe = Batch.objects.create(
            id=uuid.UUID("00000000-0000-4000-8000-000000000002"),
            owner=self.user,
            name="Second visual traditional",
            start_date=self.batch.start_date,
        )
        for kind in (Addition.Kind.HONEY, Addition.Kind.FRUIT):
            Addition.objects.create(
                batch=same_recipe,
                kind=kind,
                name=kind,
                quantity="1",
                unit="lb",
            )

        as_of = date(2026, 1, 20)
        first = build_visual_mark(self.batch, on_date=as_of)
        second = build_visual_mark(same_recipe, on_date=as_of)
        next_bucket = build_visual_mark(
            self.batch,
            on_date=date(2026, 2, 2),
        )

        self.assertNotEqual(first, second)
        self.assertEqual(first["age_bucket"], 0)
        self.assertEqual(next_bucket["age_bucket"], 1)
        self.assertGreater(next_bucket["age_progress"], first["age_progress"])
        for identity_key in (
            "shape",
            "rotation",
            "scale",
            "roundness",
            "color_start",
            "color_end",
            "glow_color",
            "palette",
            "ingredient_markers",
        ):
            self.assertEqual(first[identity_key], next_bucket[identity_key])
        self.assertNotEqual(first, next_bucket)


class VisualMarkViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="visual-dashboard-owner",
            password="Visual-Dashboard-42!",
        )
        cls.batches = []
        for index in range(3):
            batch = Batch.objects.create(
                owner=cls.user,
                name=f"Visual batch {index}",
                start_date=date(2026, 6, index + 1),
            )
            Addition.objects.create(
                batch=batch,
                kind=Addition.Kind.HONEY,
                name=f"Honey {index}",
                quantity="1",
                unit="lb",
            )
            cls.batches.append(batch)

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_prefetches_additions_once_and_attaches_marks(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("tracker:dashboard"))

        self.assertEqual(response.status_code, 200)
        addition_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "tracker_addition" in query["sql"].lower()
        ]
        self.assertEqual(len(addition_queries), 1)
        self.assertTrue(
            all(hasattr(batch, "visual_mark") for batch in response.context["batches"])
        )

    def test_batch_detail_exposes_the_same_mark_on_batch_and_context(self):
        response = self.client.get(
            reverse("tracker:batch_detail", args=[self.batches[0].pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["visual_mark"],
            response.context["batch"].visual_mark,
        )

    def test_dashboard_links_to_accessible_visual_mark_guide(self):
        dashboard = self.client.get(reverse("tracker:dashboard"))
        self.assertContains(
            dashboard,
            f'{reverse("tracker:help")}#batch-marks',
        )
        self.assertContains(dashboard, "How to read batch marks")

        help_page = self.client.get(reverse("tracker:help"))
        self.assertContains(help_page, 'id="batch-marks"')
        self.assertContains(help_page, "Reading a batch visual mark")
        self.assertContains(help_page, "Deleted ingredient entries are ignored")
        self.assertContains(help_page, "The mark does not show quantities")
