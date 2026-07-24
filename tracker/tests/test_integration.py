from __future__ import annotations

import json
import re
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tracker.models import (
    Addition,
    AuditLog,
    Batch,
    BatchStatusHistory,
    GravityReading,
    LabelPrintLog,
    Observation,
    QRLink,
)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class TrackerIntegrationTests(TestCase):
    password = "A-long-test-password-42!"

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            username="meadmaker",
            password=cls.password,
        )
        cls.other_user = user_model.objects.create_user(
            username="someone-else",
            password=cls.password,
        )
        cls.staff_user = user_model.objects.create_user(
            username="cellar-admin",
            password=cls.password,
            is_staff=True,
        )
        cls.superuser = user_model.objects.create_superuser(
            username="site-owner",
            password=cls.password,
        )
        cls.batch = Batch.objects.create(
            owner=cls.owner,
            name="Summer Solstice",
            batch_number="B-001",
            style="Traditional",
            start_date="2026-06-21",
            status=Batch.Status.FERMENTING,
            volume=Decimal("5.000"),
            volume_unit="gal",
            vessel="Glass carboy",
            description="Wildflower honey test batch.",
        )
        cls.qr_link = QRLink.objects.create(
            batch=cls.batch,
            created_by=cls.owner,
        )

    def login_as_owner(self):
        self.client.force_login(self.owner)

    def batch_form_data(self, **overrides):
        data = {
            "name": "Autumn Cyser",
            "batch_number": "B-002",
            "style": "Cyser",
            "start_date": "2026-09-15",
            "volume": "18.925",
            "volume_unit": "L",
            "vessel": "Fermentation bucket",
            "description": "Apple juice and clover honey.",
        }
        data.update(overrides)
        return data

    def addition_form_data(self, **overrides):
        data = {
            "kind": Addition.Kind.HONEY,
            "name": "Wildflower honey",
            "quantity": "12.5000",
            "unit": "lb",
            "custom_unit": "this should be cleared",
            "added_at": "2026-06-21T14:25",
            "phase": Addition.Phase.MUST,
            "notes": "Mixed until completely dissolved.",
        }
        data.update(overrides)
        return data

    def gravity_form_data(self, **overrides):
        data = {
            "specific_gravity": "1.1000",
            "reading_type": GravityReading.ReadingType.ORIGINAL,
            "measured_at": "2026-06-21T15:30",
            "sample_temperature": "68.0",
            "temperature_unit": "F",
            "method": GravityReading.Method.HYDROMETER,
            "notes": "Reading taken before pitching yeast.",
        }
        data.update(overrides)
        return data

    def observation_form_data(self, **overrides):
        data = {
            "observed_at": "2026-06-22T08:15",
            "category": Observation.Category.FERMENTATION,
            "text": "Airlock is active.\nA thin foam cap has formed.",
        }
        data.update(overrides)
        return data

    def assert_local_datetime(self, value, expected):
        self.assertEqual(
            timezone.localtime(value).strftime("%Y-%m-%dT%H:%M"),
            expected,
        )

    def test_authentication_and_owner_boundaries(self):
        detail_url = reverse("tracker:batch_detail", args=[self.batch.pk])
        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('login')}?next={detail_url}",
        )

        addition = Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.HONEY,
            name="Clover honey",
            quantity=Decimal("10.0000"),
            unit="lb",
            added_at=timezone.now(),
            phase=Addition.Phase.MUST,
            recorded_by=self.owner,
        )
        self.client.force_login(self.other_user)

        foreign_get_urls = [
            detail_url,
            reverse("tracker:batch_edit", args=[self.batch.pk]),
            reverse("tracker:addition_add", args=[self.batch.pk]),
            reverse("tracker:gravity_add", args=[self.batch.pk]),
            reverse("tracker:observation_add", args=[self.batch.pk]),
            reverse("tracker:addition_edit", args=[addition.pk]),
            reverse("tracker:entry_delete", args=["addition", addition.pk]),
            reverse("tracker:label", args=[self.batch.pk]),
            reverse("tracker:qr_svg", args=[self.batch.pk]),
            reverse("tracker:batch_export", args=[self.batch.pk]),
        ]
        for url in foreign_get_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

        restore_url = reverse(
            "tracker:entry_restore",
            args=["addition", addition.pk],
        )
        self.assertEqual(self.client.post(restore_url).status_code, 404)

        response = self.client.get(reverse("tracker:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.batch.name)

        self.client.force_login(self.owner)
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.batch.name)

    def test_theme_control_offers_system_light_and_dark_on_public_pages(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-theme-select')
        self.assertContains(response, '<option value="system">System</option>', html=True)
        self.assertContains(response, '<option value="light">Light</option>', html=True)
        self.assertContains(response, '<option value="dark">Dark</option>', html=True)
        self.assertContains(response, "tracker/js/theme-init.js")

    def test_header_and_batch_marks_render_for_the_right_user(self):
        self.login_as_owner()
        response = self.client.get(reverse("tracker:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-primary-nav')
        self.assertContains(response, 'data-account-menu')
        self.assertContains(response, "New batch")
        self.assertContains(response, 'action="/accounts/logout/"')
        self.assertNotContains(response, f'href="{reverse("tracker:user_list")}"')
        self.assertContains(
            response,
            f'aria-label="Visual mark for {self.batch.name}',
        )
        self.assertContains(response, "batch-mark--shape-")

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("tracker:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("tracker:user_list")}"')

    def test_batch_create_edit_and_duplicate_number_validation(self):
        self.login_as_owner()
        response = self.client.post(
            reverse("tracker:batch_create"),
            self.batch_form_data(),
        )

        created = Batch.objects.get(owner=self.owner, batch_number="B-002")
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[created.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(created.name, "Autumn Cyser")
        self.assertEqual(created.volume, Decimal("18.925"))
        self.assertEqual(created.volume_unit, "L")
        self.assertEqual(created.status, Batch.Status.FERMENTING)
        self.assertTrue(created.qr_links.filter(is_active=True).exists())
        self.assertTrue(
            created.status_history.filter(
                status=Batch.Status.FERMENTING,
                changed_by=self.owner,
                notes="Batch created.",
            ).exists()
        )
        self.assertTrue(
            created.audit_logs.filter(
                action=AuditLog.Action.CREATE,
                actor=self.owner,
            ).exists()
        )

        edit_data = self.batch_form_data(
            name="Barrel-Aged Autumn Cyser",
            batch_number="B-002-A",
            style="Barrel-aged cyser",
            volume="5.000",
            volume_unit="gal",
            vessel="Oak barrel",
            description="Moved to a small oak barrel.",
        )
        response = self.client.post(
            reverse("tracker:batch_edit", args=[created.pk]),
            edit_data,
        )
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[created.pk]),
            fetch_redirect_response=False,
        )

        created.refresh_from_db()
        self.assertEqual(created.name, "Barrel-Aged Autumn Cyser")
        self.assertEqual(created.batch_number, "B-002-A")
        self.assertEqual(created.vessel, "Oak barrel")
        update_log = created.audit_logs.get(action=AuditLog.Action.UPDATE)
        self.assertEqual(update_log.actor, self.owner)
        self.assertIn("name", update_log.changes)
        self.assertIn("batch_number", update_log.changes)

        response = self.client.post(
            reverse("tracker:batch_create"),
            self.batch_form_data(batch_number=self.batch.batch_number),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "You already have an active batch with this batch number.",
        )
        self.assertEqual(
            Batch.objects.filter(
                owner=self.owner,
                batch_number=self.batch.batch_number,
            ).count(),
            1,
        )

    def test_addition_create_and_edit_preserves_recording_metadata(self):
        self.login_as_owner()
        response = self.client.post(
            reverse("tracker:addition_add", args=[self.batch.pk]),
            self.addition_form_data(),
        )

        addition = self.batch.additions.get(name="Wildflower honey")
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(addition.quantity, Decimal("12.5000"))
        self.assertEqual(addition.unit, "lb")
        self.assertEqual(addition.custom_unit, "")
        self.assertEqual(addition.recorded_by, self.owner)
        self.assert_local_datetime(addition.added_at, "2026-06-21T14:25")
        original_recorded_at = addition.recorded_at

        response = self.client.post(
            reverse(
                "tracker:addition_edit",
                args=[addition.pk],
            ),
            self.addition_form_data(
                kind=Addition.Kind.FRUIT,
                name="Tart cherries",
                quantity="4.2500",
                unit="kg",
                added_at="2026-07-03T10:05",
                phase=Addition.Phase.SECONDARY,
                notes="Fruit was frozen, thawed, and bagged.",
            ),
        )
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )

        addition.refresh_from_db()
        self.assertEqual(addition.kind, Addition.Kind.FRUIT)
        self.assertEqual(addition.name, "Tart cherries")
        self.assertEqual(addition.quantity, Decimal("4.2500"))
        self.assertEqual(addition.phase, Addition.Phase.SECONDARY)
        self.assert_local_datetime(addition.added_at, "2026-07-03T10:05")
        self.assertEqual(addition.recorded_at, original_recorded_at)
        self.assertEqual(
            AuditLog.objects.filter(
                object_id=addition.pk,
                action=AuditLog.Action.CREATE,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                object_id=addition.pk,
                action=AuditLog.Action.UPDATE,
            ).count(),
            1,
        )

    def test_gravity_timestamp_is_editable_and_duplicate_og_is_rejected(self):
        self.login_as_owner()
        add_url = reverse("tracker:gravity_add", args=[self.batch.pk])
        response = self.client.post(add_url, self.gravity_form_data())

        reading = self.batch.gravity_readings.get(
            reading_type=GravityReading.ReadingType.ORIGINAL
        )
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(reading.specific_gravity, Decimal("1.1000"))
        self.assertEqual(reading.recorded_by, self.owner)
        self.assert_local_datetime(reading.measured_at, "2026-06-21T15:30")
        original_recorded_at = reading.recorded_at

        duplicate_response = self.client.post(
            add_url,
            self.gravity_form_data(
                specific_gravity="1.0980",
                measured_at="2026-06-21T15:45",
            ),
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertContains(
            duplicate_response,
            "This batch already has a Original gravity (OG).",
        )
        self.assertEqual(
            self.batch.gravity_readings.filter(
                reading_type=GravityReading.ReadingType.ORIGINAL
            ).count(),
            1,
        )

        response = self.client.post(
            reverse(
                "tracker:gravity_edit",
                args=[reading.pk],
            ),
            self.gravity_form_data(
                specific_gravity="1.0975",
                measured_at="2026-06-20T21:10",
                sample_temperature="67.5",
                notes="Corrected from the handwritten brew sheet.",
            ),
        )
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )

        reading.refresh_from_db()
        self.assertEqual(reading.specific_gravity, Decimal("1.0975"))
        self.assert_local_datetime(reading.measured_at, "2026-06-20T21:10")
        self.assertEqual(reading.sample_temperature, Decimal("67.50"))
        self.assertEqual(reading.recorded_at, original_recorded_at)

    def test_gravity_roles_are_database_unique_and_conflicting_restore_is_blocked(self):
        original = GravityReading.objects.create(
            batch=self.batch,
            specific_gravity=Decimal("1.1000"),
            reading_type=GravityReading.ReadingType.ORIGINAL,
            measured_at=timezone.now(),
            recorded_by=self.owner,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            GravityReading.objects.create(
                batch=self.batch,
                specific_gravity=Decimal("1.0990"),
                reading_type=GravityReading.ReadingType.ORIGINAL,
                measured_at=timezone.now(),
                recorded_by=self.owner,
            )

        original.delete()
        replacement = GravityReading.objects.create(
            batch=self.batch,
            specific_gravity=Decimal("1.0980"),
            reading_type=GravityReading.ReadingType.ORIGINAL,
            measured_at=timezone.now(),
            recorded_by=self.owner,
        )
        self.login_as_owner()
        response = self.client.post(
            reverse(
                "tracker:entry_restore",
                args=["gravity", original.pk],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "already has an active reading with that OG/FG role",
        )
        self.assertIsNotNone(
            GravityReading.all_objects.get(pk=original.pk).deleted_at
        )
        self.assertEqual(
            list(
                self.batch.gravity_readings.filter(
                    reading_type=GravityReading.ReadingType.ORIGINAL
                ).values_list("pk", flat=True)
            ),
            [replacement.pk],
        )

    def test_backdated_status_history_does_not_replace_current_status(self):
        self.login_as_owner()
        status_url = reverse("tracker:status_update", args=[self.batch.pk])

        response = self.client.post(
            status_url,
            {
                "status": Batch.Status.AGING,
                "changed_at": "2026-07-20T12:00",
                "notes": "Moved to bulk aging.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, Batch.Status.AGING)

        response = self.client.post(
            status_url,
            {
                "status": Batch.Status.CONDITIONING,
                "changed_at": "2026-07-01T09:30",
                "notes": "Historical note entered later.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Historical status recorded; the batch&#x27;s current status was left unchanged.",
            html=True,
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, Batch.Status.AGING)
        audit = self.batch.audit_logs.filter(action=AuditLog.Action.STATUS).latest(
            "recorded_at"
        )
        self.assertEqual(
            audit.changes["status"],
            {
                "before": Batch.Status.AGING,
                "after": Batch.Status.AGING,
            },
        )
        self.assertEqual(
            audit.changes["recorded_history"]["status"],
            Batch.Status.CONDITIONING,
        )

    def test_current_status_timing_can_be_restored_once_when_history_is_missing(
        self,
    ):
        self.login_as_owner()
        status_url = reverse("tracker:status_update", args=[self.batch.pk])
        self.assertFalse(
            self.batch.status_history.filter(
                status=Batch.Status.FERMENTING
            ).exists()
        )

        response = self.client.post(
            status_url,
            {
                "status": Batch.Status.FERMENTING,
                "changed_at": "2026-07-24T13:30",
                "notes": "Restored the missing start time.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fermenting timing recorded.")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, Batch.Status.FERMENTING)
        self.assertEqual(
            self.batch.status_history.filter(
                status=Batch.Status.FERMENTING
            ).count(),
            1,
        )

        duplicate_response = self.client.post(
            status_url,
            {
                "status": Batch.Status.FERMENTING,
                "changed_at": "2026-07-24T13:45",
                "notes": "Duplicate timing.",
            },
        )

        self.assertEqual(duplicate_response.status_code, 200)
        self.assertContains(
            duplicate_response,
            "Choose a different status for this batch.",
        )
        self.assertEqual(
            self.batch.status_history.filter(
                status=Batch.Status.FERMENTING
            ).count(),
            1,
        )

    def test_free_text_observation_create_and_edit(self):
        self.login_as_owner()
        response = self.client.post(
            reverse("tracker:observation_add", args=[self.batch.pk]),
            self.observation_form_data(),
        )

        observation = self.batch.observations.get()
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            observation.text,
            "Airlock is active.\nA thin foam cap has formed.",
        )
        self.assertEqual(observation.recorded_by, self.owner)
        self.assert_local_datetime(observation.observed_at, "2026-06-22T08:15")
        original_recorded_at = observation.recorded_at

        response = self.client.post(
            reverse(
                "tracker:observation_edit",
                args=[observation.pk],
            ),
            self.observation_form_data(
                observed_at="2026-06-23T18:40",
                category=Observation.Category.AROMA,
                text="Orange blossom aroma.\nNo sulfur character noticed.",
            ),
        )
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )

        observation.refresh_from_db()
        self.assertEqual(observation.category, Observation.Category.AROMA)
        self.assertEqual(
            observation.text,
            "Orange blossom aroma.\nNo sulfur character noticed.",
        )
        self.assert_local_datetime(observation.observed_at, "2026-06-23T18:40")
        self.assertEqual(observation.recorded_at, original_recorded_at)

    def test_entry_soft_delete_and_restore_are_owner_only_and_audited(self):
        addition = Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.SPICE,
            name="Cinnamon stick",
            quantity=Decimal("1.0000"),
            unit="count",
            added_at=timezone.now(),
            phase=Addition.Phase.CONDITIONING,
            recorded_by=self.owner,
        )
        delete_url = reverse(
            "tracker:entry_delete",
            args=["addition", addition.pk],
        )
        restore_url = reverse(
            "tracker:entry_restore",
            args=["addition", addition.pk],
        )
        self.login_as_owner()

        response = self.client.post(delete_url, {"confirm": "on"})
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(Addition.objects.filter(pk=addition.pk).exists())
        removed = Addition.all_objects.get(pk=addition.pk)
        self.assertIsNotNone(removed.deleted_at)
        self.assertTrue(
            AuditLog.objects.filter(
                object_id=addition.pk,
                action=AuditLog.Action.DELETE,
                actor=self.owner,
            ).exists()
        )
        self.assertEqual(self.client.get(restore_url).status_code, 405)

        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(restore_url).status_code, 404)
        self.assertFalse(Addition.objects.filter(pk=addition.pk).exists())

        self.login_as_owner()
        response = self.client.post(restore_url)
        self.assertRedirects(
            response,
            reverse("tracker:batch_detail", args=[self.batch.pk]),
            fetch_redirect_response=False,
        )
        restored = Addition.objects.get(pk=addition.pk)
        self.assertIsNone(restored.deleted_at)
        self.assertTrue(
            AuditLog.objects.filter(
                object_id=addition.pk,
                action=AuditLog.Action.RESTORE,
                actor=self.owner,
            ).exists()
        )

    def test_qr_deep_link_survives_login_and_opens_mobile_batch(self):
        target = reverse("tracker:qr_batch", args=[self.qr_link.token])
        response = self.client.get(target)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('login')}?next={target}")

        response = self.client.post(
            reverse("login"),
            {
                "username": self.owner.username,
                "password": self.password,
                "next": target,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)

        response = self.client.get(target)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tracker/mobile_batch.html")
        self.assertTrue(response.context["mobile_quick_entry"])
        self.assertEqual(response.context["batch"], self.batch)
        self.qr_link.refresh_from_db()
        self.assertEqual(self.qr_link.scan_count, 1)
        self.assertIsNotNone(self.qr_link.last_scanned_at)

        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(target).status_code, 404)
        self.qr_link.refresh_from_db()
        self.assertEqual(self.qr_link.scan_count, 1)

    @override_settings(PUBLIC_BASE_URL="https://mead.example.test:9443")
    def test_qr_svg_and_configured_public_base_url(self):
        self.login_as_owner()
        label_response = self.client.get(
            reverse("tracker:label", args=[self.batch.pk])
        )
        expected_target = (
            "https://mead.example.test:9443"
            + reverse("tracker:qr_batch", args=[self.qr_link.token])
        )
        self.assertEqual(label_response.status_code, 200)
        self.assertEqual(label_response.context["qr_url"], expected_target)
        self.assertEqual(label_response.context["base_url_warning"], "")

        response = self.client.get(
            reverse("tracker:qr_svg", args=[self.batch.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Type"],
            "image/svg+xml; charset=utf-8",
        )
        self.assertEqual(response.headers["Cache-Control"], "private, max-age=300")
        svg = response.content.decode("utf-8")
        self.assertIn("<svg", svg)
        self.assertIn('class="segno"', svg)
        self.assertIn('class="qrline"', svg)

    def test_exact_size_pdf_label_response_and_print_log(self):
        self.login_as_owner()
        response = self.client.get(
            reverse("tracker:label_pdf", args=[self.batch.pk]),
            {
                "preset": "3x4",
                "dimension_unit": "in",
                "output_mode": "single",
                "copies": "1",
                "include_batch_number": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/pdf")
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="summer-solstice-label.pdf"',
        )
        self.assertTrue(response.content.startswith(b"%PDF-"))
        match = re.search(
            rb"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+"
            rb"([0-9.]+)\s+([0-9.]+)\s*\]",
            response.content,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            tuple(float(value) for value in match.groups()),
            (0.0, 0.0, 216.0, 288.0),
        )

        print_log = LabelPrintLog.objects.get(batch=self.batch)
        self.assertEqual(print_log.printed_by, self.owner)
        self.assertEqual(print_log.qr_link, self.qr_link)
        self.assertEqual(print_log.label_preset, "3x4")
        self.assertEqual(print_log.width, Decimal("3.000"))
        self.assertEqual(print_log.height, Decimal("4.000"))
        self.assertEqual(print_log.dimension_unit, "in")
        self.assertEqual(print_log.output_mode, "single")
        self.assertEqual(print_log.copies, 1)

        invalid_response = self.client.get(
            reverse("tracker:label_pdf", args=[self.batch.pk]),
            {
                "preset": "custom",
                "width": "0.25",
                "height": "4",
                "dimension_unit": "in",
                "output_mode": "single",
                "copies": "1",
            },
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(LabelPrintLog.objects.filter(batch=self.batch).count(), 1)

    def test_json_export_contains_active_batch_history_and_entries(self):
        BatchStatusHistory.objects.create(
            batch=self.batch,
            status=Batch.Status.FERMENTING,
            changed_at=timezone.now(),
            notes="Batch created.",
            changed_by=self.owner,
        )
        active_addition = Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.HONEY,
            name="Orange blossom honey",
            quantity=Decimal("11.2500"),
            unit="lb",
            added_at=timezone.now(),
            phase=Addition.Phase.MUST,
            notes="Primary fermentable.",
            recorded_by=self.owner,
        )
        removed_addition = Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.SPICE,
            name="Removed clove",
            quantity=Decimal("1.0000"),
            unit="count",
            added_at=timezone.now(),
            phase=Addition.Phase.MUST,
            recorded_by=self.owner,
        )
        removed_addition.delete()
        gravity = GravityReading.objects.create(
            batch=self.batch,
            specific_gravity=Decimal("1.1050"),
            reading_type=GravityReading.ReadingType.ORIGINAL,
            measured_at=timezone.now(),
            sample_temperature=Decimal("68.00"),
            temperature_unit="F",
            method=GravityReading.Method.HYDROMETER,
            notes="OG",
            recorded_by=self.owner,
        )
        observation = Observation.objects.create(
            batch=self.batch,
            observed_at=timezone.now(),
            category=Observation.Category.AROMA,
            text="Fresh orange blossom aroma.",
            recorded_by=self.owner,
        )

        self.login_as_owner()
        response = self.client.get(
            reverse("tracker:batch_export", args=[self.batch.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(
            response.headers["Content-Disposition"],
            f'attachment; filename="mead-batch-{self.batch.pk}.json"',
        )

        payload = json.loads(response.content)
        self.assertEqual(payload["format"], "mead-tracker-batch")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["batch"]["id"], str(self.batch.pk))
        self.assertEqual(payload["batch"]["name"], self.batch.name)
        self.assertEqual(payload["batch"]["batch_number"], "B-001")
        self.assertEqual(
            [item["id"] for item in payload["batch"]["additions"]],
            [str(active_addition.pk)],
        )
        self.assertEqual(
            payload["batch"]["additions"][0]["quantity"],
            "11.2500",
        )
        self.assertEqual(
            payload["batch"]["gravity_readings"][0]["id"],
            str(gravity.pk),
        )
        self.assertEqual(
            payload["batch"]["observations"][0]["id"],
            str(observation.pk),
        )
        self.assertEqual(
            payload["batch"]["status_history"][0]["status"],
            Batch.Status.FERMENTING,
        )
        self.assertNotIn("qr_links", payload["batch"])
        self.assertNotIn("audit_logs", payload["batch"])

    @patch(
        "tracker.views.create_backup_bytes",
        return_value=(
            b"SQLite format 3\x00verified-test-backup",
            "mead-tracker-20260724-120000.sqlite3",
        ),
    )
    def test_database_backup_is_staff_only(self, create_backup_mock):
        backup_url = reverse("tracker:database_backup")

        response = self.client.get(backup_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('login')}?next={backup_url}",
        )

        self.client.force_login(self.owner)
        response = self.client.get(backup_url)
        self.assertEqual(response.status_code, 403)
        create_backup_mock.assert_not_called()

        self.client.force_login(self.staff_user)
        response = self.client.get(backup_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Type"],
            "application/vnd.sqlite3",
        )
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="mead-tracker-20260724-120000.sqlite3"',
        )
        self.assertTrue(response.content.startswith(b"SQLite format 3\x00"))
        create_backup_mock.assert_called_once_with()

    def test_health_endpoint_is_public_and_reports_database_state(self):
        response = self.client.get(reverse("tracker:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

        with patch(
            "tracker.views.connection.cursor",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self.client.get(reverse("tracker:health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unhealthy"})
