from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from tracker.models import AuditLog, Batch


class AccountManagementTests(TestCase):
    password = "River-Glass-Honey-42!"

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.superuser = user_model.objects.create_superuser(
            username="cellar-owner",
            email="owner@example.test",
            password=cls.password,
        )
        cls.user = user_model.objects.create_user(
            username="batch-maker",
            email="maker@example.test",
            password=cls.password,
        )
        cls.staff_user = user_model.objects.create_user(
            username="staff-only",
            password=cls.password,
            is_staff=True,
        )

        cls.active_batch = Batch.objects.create(
            owner=cls.user,
            name="Active traditional",
            start_date=date(2026, 7, 1),
            status=Batch.Status.FERMENTING,
            volume=Decimal("5.000"),
            volume_unit="gal",
        )
        cls.removed_batch = Batch.objects.create(
            owner=cls.user,
            name="Removed cyser",
            start_date=date(2026, 6, 1),
            status=Batch.Status.ARCHIVED,
        )
        cls.removed_batch.delete()

    def test_user_console_is_superuser_only_and_reports_batch_counts(self):
        url = reverse("tracker:user_list")
        create_url = reverse("tracker:user_create")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('login')}?next={url}")

        for unauthorized_user in (self.user, self.staff_user):
            with self.subTest(username=unauthorized_user.username):
                self.client.force_login(unauthorized_user)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.get(create_url).status_code, 403)
                self.assertEqual(
                    self.client.post(
                        reverse(
                            "tracker:user_deactivate",
                            args=[self.superuser.pk],
                        )
                    ).status_code,
                    403,
                )

        self.client.force_login(self.superuser)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        managed_user = next(
            item
            for item in response.context["users"]
            if item.pk == self.user.pk
        )
        self.assertEqual(managed_user.active_batch_count, 1)
        self.assertEqual(managed_user.total_batch_count, 2)
        self.assertContains(response, self.user.username)
        self.assertContains(response, "2 total")

    def test_superuser_can_create_a_regular_user_with_validated_password(self):
        self.client.force_login(self.superuser)
        create_url = reverse("tracker:user_create")
        form_response = self.client.get(create_url)
        self.assertEqual(form_response.status_code, 200)
        self.assertTemplateUsed(form_response, "tracker/user_form.html")

        response = self.client.post(
            create_url,
            {
                "username": "new-meadmaker",
                "email": "new@example.test",
                "first_name": "New",
                "last_name": "Maker",
                "password1": "Clover-Orchard-Bottle-73!",
                "password2": "Clover-Orchard-Bottle-73!",
                "is_staff": "on",
                "is_superuser": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("tracker:user_list"),
            fetch_redirect_response=False,
        )
        created = get_user_model().objects.get(username="new-meadmaker")
        self.assertTrue(created.check_password("Clover-Orchard-Bottle-73!"))
        self.assertTrue(created.is_active)
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertEqual(created.get_full_name(), "New Maker")
        audit = AuditLog.objects.get(
            actor=self.superuser,
            action=AuditLog.Action.CREATE,
            model_name=created._meta.label_lower,
        )
        self.assertEqual(audit.changes["created"]["user_id"], created.pk)
        self.assertEqual(audit.changes["created"]["source"], "superuser")

    def test_deactivation_preserves_batches_and_reactivation_restores_access(self):
        user_client = Client()
        self.assertTrue(
            user_client.login(
                username=self.user.username,
                password=self.password,
            )
        )
        user_session_key = user_client.session.session_key
        self.assertTrue(Session.objects.filter(pk=user_session_key).exists())

        self.client.force_login(self.superuser)
        deactivate_url = reverse(
            "tracker:user_deactivate",
            args=[self.user.pk],
        )
        reactivate_url = reverse(
            "tracker:user_reactivate",
            args=[self.user.pk],
        )

        self.assertEqual(self.client.get(deactivate_url).status_code, 405)
        response = self.client.post(deactivate_url)
        self.assertRedirects(
            response,
            reverse("tracker:user_list"),
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(Session.objects.filter(pk=user_session_key).exists())
        self.assertEqual(
            Batch.all_objects.filter(owner=self.user).count(),
            2,
        )
        audit = AuditLog.objects.get(
            actor=self.superuser,
            action=AuditLog.Action.UPDATE,
            model_name=self.user._meta.label_lower,
        )
        self.assertEqual(audit.changes["user_id"], self.user.pk)
        self.assertEqual(
            audit.changes["is_active"],
            {"before": True, "after": False},
        )
        self.assertEqual(audit.changes["sessions_revoked"], 1)

        response = self.client.post(reactivate_url)
        self.assertRedirects(
            response,
            reverse("tracker:user_list"),
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        dashboard_url = reverse("tracker:dashboard")
        response = user_client.get(dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('login')}?next={dashboard_url}",
        )

    def test_superuser_cannot_deactivate_their_own_account(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse(
                "tracker:user_deactivate",
                args=[self.superuser.pk],
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)
        self.assertContains(response, "cannot deactivate your own account")

    @override_settings(ALLOW_SIGNUPS=True)
    def test_signup_creates_only_a_regular_user_and_logs_them_in(self):
        signup_url = reverse("tracker:signup")
        login_response = self.client.get(reverse("login"))
        self.assertContains(login_response, signup_url)

        response = self.client.post(
            signup_url,
            {
                "username": "self-registered",
                "email": "registered@example.test",
                "first_name": "Self",
                "last_name": "Registered",
                "password1": "Heather-Cellar-Journal-84!",
                "password2": "Heather-Cellar-Journal-84!",
                "next": reverse("tracker:help"),
                "is_staff": "on",
                "is_superuser": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("tracker:help"),
            fetch_redirect_response=False,
        )
        created = get_user_model().objects.get(username="self-registered")
        self.assertTrue(created.is_active)
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            created.pk,
        )
        audit = AuditLog.objects.get(
            actor=created,
            action=AuditLog.Action.CREATE,
            model_name=created._meta.label_lower,
        )
        self.assertEqual(audit.changes["created"]["user_id"], created.pk)
        self.assertEqual(audit.changes["created"]["source"], "public_signup")

    @override_settings(ALLOW_SIGNUPS=True)
    def test_signup_rejects_a_weak_password(self):
        response = self.client.post(
            reverse("tracker:signup"),
            {
                "username": "weak-password",
                "email": "",
                "first_name": "",
                "last_name": "",
                "password1": "12345678",
                "password2": "12345678",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            get_user_model().objects.filter(username="weak-password").exists()
        )
        password_errors = response.context["form"].errors.as_data()["password2"]
        self.assertIn(
            "password_too_common",
            {error.code for error in password_errors},
        )

    @override_settings(ALLOW_SIGNUPS=True)
    def test_signup_rejects_an_external_next_url(self):
        response = self.client.post(
            reverse("tracker:signup"),
            {
                "username": "safe-redirect",
                "email": "",
                "first_name": "",
                "last_name": "",
                "password1": "Heather-Cellar-Journal-85!",
                "password2": "Heather-Cellar-Journal-85!",
                "next": "https://malicious.example/collect",
            },
        )

        self.assertRedirects(
            response,
            reverse("tracker:dashboard"),
            fetch_redirect_response=False,
        )

    @override_settings(ALLOW_SIGNUPS=False)
    def test_disabled_signup_is_hidden_and_returns_not_found(self):
        signup_url = reverse("tracker:signup")

        self.assertNotContains(self.client.get(reverse("login")), signup_url)
        self.assertEqual(self.client.get(signup_url).status_code, 404)
        response = self.client.post(
            signup_url,
            {
                "username": "blocked-registration",
                "password1": "Heather-Cellar-Journal-84!",
                "password2": "Heather-Cellar-Journal-84!",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            get_user_model().objects.filter(
                username="blocked-registration"
            ).exists()
        )
