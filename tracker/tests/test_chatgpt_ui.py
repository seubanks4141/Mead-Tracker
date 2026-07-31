from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tracker.models import Batch


class ChatGPTBatchCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(
            username="chatgpt-brewer",
            password="A-long-test-password-42!",
        )
        cls.batch = Batch.objects.create(
            owner=cls.owner,
            name="Orange Blossom Traditional",
            batch_number="AI-001",
        )

    @override_settings(
        CHATGPT_ENABLED=True,
        CHATGPT_OAUTH_CALLBACK_URL=(
            "https://chatgpt.com/connector/oauth/ui-card-test"
        ),
    )
    def test_owner_sees_active_chatgpt_batch_card(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("tracker:batch_detail", args=[self.batch.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ask about this batch")
        self.assertContains(response, "Uses your ChatGPT plan")
        self.assertContains(
            response,
            f'id="assistant-prompt-{self.batch.pk}"',
        )
        self.assertContains(
            response,
            f'data-copy-prompt="assistant-prompt-{self.batch.pk}"',
        )
        self.assertContains(response, "Fetch its latest complete batch context")
        self.assertContains(response, f"batch ID {self.batch.pk}")
        self.assertNotContains(
            response,
            f'review batch "{self.batch.name}"',
        )
        self.assertContains(response, 'href="https://chatgpt.com/"')
        self.assertContains(response, "Open ChatGPT")
        self.assertContains(response, 'href="https://chatgpt.com/plugins"')
        self.assertNotContains(response, "Planned update")
        self.assertNotContains(response, "Coming later")
        self.assertNotContains(response, "side-card--future")

    @override_settings(CHATGPT_ENABLED=False)
    def test_card_is_hidden_until_the_integration_is_configured(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("tracker:batch_detail", args=[self.batch.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Ask about this batch")
        self.assertNotContains(response, "Uses your ChatGPT plan")

    @override_settings(
        CHATGPT_ENABLED=True,
        CHATGPT_OAUTH_CALLBACK_URL="",
    )
    def test_card_is_hidden_during_callback_bootstrap(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("tracker:batch_detail", args=[self.batch.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Ask about this batch")
        self.assertNotContains(response, "Uses your ChatGPT plan")
