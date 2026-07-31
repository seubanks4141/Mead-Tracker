from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tracker.models import (
    Addition,
    AuditLog,
    Batch,
    BatchStatusHistory,
    GravityReading,
    Observation,
    QRLink,
)
from tracker.services.batch_context import get_owned_batch_context


class BatchContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            username="context-owner",
            password="Context-Honey-42!",
        )
        cls.other_user = user_model.objects.create_user(
            username="context-outsider",
            password="Context-Honey-42!",
        )
        cls.started_at = timezone.make_aware(datetime(2026, 7, 1, 9, 30))
        cls.batch = Batch.objects.create(
            owner=cls.owner,
            name="Canonical traditional",
            batch_number="CTX-001",
            style="Traditional",
            start_date=cls.started_at.date(),
            fermentation_started_at=cls.started_at,
            target_fermentation_sg=Decimal("1.0100"),
            planned_conditioning_days=45,
            status=Batch.Status.FERMENTING,
            volume=Decimal("5.000"),
            volume_unit="gal",
            vessel="Glass carboy",
            description="Orange blossom honey test batch.",
        )
        cls.status_history = BatchStatusHistory.objects.create(
            batch=cls.batch,
            status=Batch.Status.FERMENTING,
            changed_at=cls.started_at,
            notes="Yeast pitched.",
            changed_by=cls.owner,
        )
        cls.addition = Addition.objects.create(
            batch=cls.batch,
            kind=Addition.Kind.HONEY,
            name="Orange blossom honey",
            quantity=Decimal("12.5000"),
            unit="lb",
            added_at=cls.started_at,
            phase=Addition.Phase.MUST,
            notes="Primary fermentable.",
            recorded_by=cls.owner,
        )
        removed_addition = Addition.objects.create(
            batch=cls.batch,
            kind=Addition.Kind.SPICE,
            name="Removed secret clove",
            quantity=Decimal("1.0000"),
            unit="count",
            added_at=cls.started_at + timedelta(minutes=1),
            phase=Addition.Phase.MUST,
            recorded_by=cls.owner,
        )
        removed_addition.delete()
        cls.original_gravity = GravityReading.objects.create(
            batch=cls.batch,
            specific_gravity=Decimal("1.1000"),
            reading_type=GravityReading.ReadingType.ORIGINAL,
            measured_at=cls.started_at + timedelta(hours=1),
            sample_temperature=Decimal("68.00"),
            temperature_unit="F",
            method=GravityReading.Method.HYDROMETER,
            notes="Before pitching.",
            recorded_by=cls.owner,
        )
        cls.routine_gravity = GravityReading.objects.create(
            batch=cls.batch,
            specific_gravity=Decimal("1.0600"),
            reading_type=GravityReading.ReadingType.ROUTINE,
            measured_at=cls.started_at + timedelta(days=4),
            method=GravityReading.Method.HYDROMETER,
            notes="Fermentation is active.",
            recorded_by=cls.owner,
        )
        removed_gravity = GravityReading.objects.create(
            batch=cls.batch,
            specific_gravity=Decimal("1.0500"),
            reading_type=GravityReading.ReadingType.ROUTINE,
            measured_at=cls.started_at + timedelta(days=5),
            method=GravityReading.Method.OTHER,
            notes="Removed secret gravity.",
            recorded_by=cls.owner,
        )
        removed_gravity.delete()
        cls.observation = Observation.objects.create(
            batch=cls.batch,
            observed_at=cls.started_at + timedelta(days=2),
            category=Observation.Category.AROMA,
            text="Floral aroma and steady bubbles.",
            photo="observation_photos/secret-storage-name.jpg",
            recorded_by=cls.owner,
        )
        removed_observation = Observation.objects.create(
            batch=cls.batch,
            observed_at=cls.started_at + timedelta(days=3),
            category=Observation.Category.ISSUE,
            text="Removed secret observation.",
            recorded_by=cls.owner,
        )
        removed_observation.delete()
        QRLink.objects.create(
            batch=cls.batch,
            token="secret-qr-token",
            created_by=cls.owner,
        )
        AuditLog.objects.create(
            batch=cls.batch,
            actor=cls.owner,
            action=AuditLog.Action.UPDATE,
            model_name=Batch._meta.label_lower,
            object_id=cls.batch.pk,
            object_repr=str(cls.batch),
            changes={"private_audit_value": "secret-audit-value"},
        )

    def context(self, *, generated_at=None):
        return get_owned_batch_context(
            owner=self.owner,
            batch_id=self.batch.pk,
            generated_at=generated_at,
        )

    def test_context_is_complete_json_encodable_and_export_compatible(self):
        generated_at = self.started_at + timedelta(days=7)

        payload = self.context(generated_at=generated_at)
        batch_data = payload["batch"]

        self.assertEqual(payload["format"], "mead-tracker-batch")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(
            payload["exported_at"],
            json.loads(json.dumps(generated_at, cls=DjangoJSONEncoder)),
        )
        self.assertRegex(payload["content_revision"], r"^[0-9a-f]{64}$")
        self.assertEqual(batch_data["id"], str(self.batch.pk))
        self.assertEqual(batch_data["name"], self.batch.name)
        self.assertEqual(batch_data["batch_number"], "CTX-001")
        self.assertEqual(batch_data["target_fermentation_sg"], "1.0100")
        self.assertEqual(batch_data["planned_conditioning_days"], 45)
        self.assertEqual(batch_data["summary"]["original_gravity"], "1.1000")
        self.assertEqual(batch_data["summary"]["latest_gravity"], "1.0600")
        self.assertEqual(batch_data["summary"]["estimated_abv"], "5.2")
        self.assertFalse(batch_data["summary"]["estimated_abv_is_final"])

        self.assertEqual(
            [item["id"] for item in batch_data["additions"]],
            [str(self.addition.pk)],
        )
        self.assertEqual(
            [item["id"] for item in batch_data["gravity_readings"]],
            [str(self.original_gravity.pk), str(self.routine_gravity.pk)],
        )
        self.assertEqual(
            [item["id"] for item in batch_data["observations"]],
            [str(self.observation.pk)],
        )
        self.assertTrue(batch_data["observations"][0]["has_photo"])
        self.assertEqual(
            [item["id"] for item in batch_data["status_history"]],
            [str(self.status_history.pk)],
        )

        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["batch"]["volume"], "5.000")
        self.assertEqual(
            decoded["batch"]["additions"][0]["quantity"],
            "12.5000",
        )

    def test_context_omits_deleted_and_private_operational_data(self):
        encoded = json.dumps(self.context(), cls=DjangoJSONEncoder)

        self.assertNotIn("Removed secret clove", encoded)
        self.assertNotIn("Removed secret gravity", encoded)
        self.assertNotIn("Removed secret observation", encoded)
        self.assertNotIn("secret-storage-name", encoded)
        self.assertNotIn("secret-qr-token", encoded)
        self.assertNotIn("secret-audit-value", encoded)
        self.assertNotIn(self.owner.username, encoded)
        self.assertNotIn(self.other_user.username, encoded)

        batch_data = self.context()["batch"]
        self.assertNotIn("owner", batch_data)
        self.assertNotIn("qr_links", batch_data)
        self.assertNotIn("audit_logs", batch_data)
        self.assertNotIn("recorded_by", batch_data["additions"][0])
        self.assertNotIn("recorded_by", batch_data["gravity_readings"][0])
        self.assertNotIn("recorded_by", batch_data["observations"][0])
        self.assertNotIn("changed_by", batch_data["status_history"][0])
        self.assertNotIn("photo", batch_data["observations"][0])

    def test_owner_inactive_foreign_and_removed_batches_are_indistinguishable(self):
        with self.assertRaises(Batch.DoesNotExist):
            get_owned_batch_context(
                owner=self.other_user,
                batch_id=self.batch.pk,
            )

        removed_batch = Batch.objects.create(
            owner=self.owner,
            name="Removed batch",
        )
        removed_batch.delete()
        with self.assertRaises(Batch.DoesNotExist):
            get_owned_batch_context(
                owner=self.owner,
                batch_id=removed_batch.pk,
            )

        inactive_batch = Batch.objects.create(
            owner=self.other_user,
            name="Inactive owner's batch",
        )
        self.other_user.is_active = False
        self.other_user.save(update_fields=["is_active"])
        with self.assertRaises(Batch.DoesNotExist):
            get_owned_batch_context(
                owner=self.other_user,
                batch_id=inactive_batch.pk,
            )

    def test_context_refresh_reflects_child_create_edit_and_delete(self):
        initial = self.context()

        nutrient = Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.NUTRIENT,
            name="Fermaid O",
            quantity=Decimal("4.0000"),
            unit="g",
            added_at=self.started_at + timedelta(days=1),
            phase=Addition.Phase.PRIMARY,
            notes="First nutrient addition.",
            recorded_by=self.owner,
        )
        created = self.context()
        self.assertNotEqual(
            created["content_revision"],
            initial["content_revision"],
        )
        self.assertIn(
            str(nutrient.pk),
            [item["id"] for item in created["batch"]["additions"]],
        )

        nutrient.name = "Fermaid O nutrient"
        nutrient.save(update_fields=["name", "updated_at"])
        edited = self.context()
        self.assertNotEqual(
            edited["content_revision"],
            created["content_revision"],
        )
        self.assertIn(
            "Fermaid O nutrient",
            [item["name"] for item in edited["batch"]["additions"]],
        )

        nutrient.delete()
        deleted = self.context()
        self.assertNotEqual(
            deleted["content_revision"],
            edited["content_revision"],
        )
        self.assertNotIn(
            str(nutrient.pk),
            [item["id"] for item in deleted["batch"]["additions"]],
        )

    def test_revision_is_stable_when_only_generation_time_changes(self):
        first = self.context(generated_at=self.started_at)
        second = self.context(generated_at=self.started_at + timedelta(hours=1))

        self.assertNotEqual(first["exported_at"], second["exported_at"])
        self.assertEqual(first["content_revision"], second["content_revision"])

    def test_context_query_count_is_fixed(self):
        with self.assertNumQueries(5):
            self.context()

    def test_existing_export_route_uses_the_canonical_payload(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("tracker:batch_export", args=[self.batch.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(
            response.headers["Content-Disposition"],
            f'attachment; filename="mead-batch-{self.batch.pk}.json"',
        )
        payload = response.json()
        self.assertEqual(payload["format"], "mead-tracker-batch")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["batch"]["id"], str(self.batch.pk))
        self.assertEqual(
            payload["batch"]["additions"][0]["quantity"],
            "12.5000",
        )
        self.assertIn("content_revision", payload)
