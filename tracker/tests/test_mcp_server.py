from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import (
    AccessToken as OAuthAccessToken,
    Application,
)
from mcp_types.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

from mead_tracker.mcp_server import (
    MAX_BATCH_CONTEXT_UTF8_BYTES,
    MAX_BATCH_LIST_OFFSET,
    MAX_BATCH_LIST_RESULTS,
    MAX_BATCH_SEARCH_QUERY_LENGTH,
    OAUTH_TOOL_META,
    READ_SCOPE,
    ListBatchesOutput,
    MeadOAuthTokenVerifier,
    create_mcp_application,
    get_batch_context_for_owner,
    list_batches_for_owner,
)
from tracker.models import Addition, Batch, Observation, QuantityUnit


RESOURCE_URL = "https://mead.example.test/mcp"
ORIGIN_URL = "https://mead.example.test"
ISSUER_URL = f"{ORIGIN_URL}/o"


class MCPBatchToolTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="mcp-owner",
            password="test-password",
        )
        self.other = user_model.objects.create_user(
            username="mcp-other",
            password="test-password",
        )
        self.batch = Batch.objects.create(
            owner=self.owner,
            name="Orange Blossom",
            batch_number="OB-01",
            style="Traditional",
            status=Batch.Status.FERMENTING,
        )
        self.foreign_batch = Batch.objects.create(
            owner=self.other,
            name="Private Cyser",
            batch_number="PC-02",
            status=Batch.Status.AGING,
        )

    def test_list_batches_is_owner_scoped_and_searchable(self):
        result = list_batches_for_owner(
            owner_id=str(self.owner.pk),
            query="orange",
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_offset"])
        self.assertEqual(result["batches"][0]["id"], str(self.batch.pk))
        self.assertNotIn(str(self.foreign_batch.pk), str(result))

    def test_list_batches_paginates_without_silently_hiding_matches(self):
        second = Batch.objects.create(
            owner=self.owner,
            name="Second",
            status=Batch.Status.AGING,
        )
        third = Batch.objects.create(
            owner=self.owner,
            name="Third",
            status=Batch.Status.COMPLETE,
        )

        first_page = list_batches_for_owner(
            owner_id=str(self.owner.pk),
            limit=2,
        )
        second_page = list_batches_for_owner(
            owner_id=str(self.owner.pk),
            limit=2,
            offset=first_page["next_offset"],
        )

        self.assertEqual(first_page["count"], 2)
        self.assertEqual(first_page["total"], 3)
        self.assertTrue(first_page["has_more"])
        self.assertEqual(first_page["next_offset"], 2)
        self.assertEqual(second_page["count"], 1)
        self.assertEqual(second_page["total"], 3)
        self.assertFalse(second_page["has_more"])
        self.assertIsNone(second_page["next_offset"])
        returned_ids = {
            item["id"]
            for item in first_page["batches"] + second_page["batches"]
        }
        self.assertEqual(
            returned_ids,
            {str(self.batch.pk), str(second.pk), str(third.pk)},
        )

    def test_list_batches_validates_status_query_limit_and_offset(self):
        with self.assertRaisesRegex(ValueError, "Unknown batch status"):
            list_batches_for_owner(
                owner_id=str(self.owner.pk),
                status="not-a-status",
            )
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            list_batches_for_owner(
                owner_id=str(self.owner.pk),
                limit=51,
            )
        with self.assertRaisesRegex(ValueError, "offset must be"):
            list_batches_for_owner(
                owner_id=str(self.owner.pk),
                offset=MAX_BATCH_LIST_OFFSET + 1,
            )
        with self.assertRaisesRegex(ValueError, "query must be"):
            list_batches_for_owner(
                owner_id=str(self.owner.pk),
                query="x" * (MAX_BATCH_SEARCH_QUERY_LENGTH + 1),
            )

    def test_next_offset_accepts_pages_beyond_the_old_ten_thousand_limit(self):
        payload = ListBatchesOutput.model_validate(
            {
                "batches": [],
                "count": 1,
                "total": 10_002,
                "result_limit": 1,
                "offset": 10_000,
                "has_more": True,
                "next_offset": 10_001,
            }
        )

        self.assertEqual(payload.next_offset, 10_001)
        self.assertLessEqual(payload.next_offset, MAX_BATCH_LIST_OFFSET)

    def test_context_is_fresh_on_every_call(self):
        before = get_batch_context_for_owner(
            owner_id=str(self.owner.pk),
            batch_id=str(self.batch.pk),
        )
        Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.NUTRIENT,
            name="Fermaid O",
            quantity="1.5000",
            unit=QuantityUnit.GRAM,
            added_at=timezone.now(),
        )

        after = get_batch_context_for_owner(
            owner_id=str(self.owner.pk),
            batch_id=str(self.batch.pk),
        )

        self.assertNotEqual(before["content_revision"], after["content_revision"])
        self.assertEqual(after["batch"]["additions"][0]["name"], "Fermaid O")

    def test_context_excludes_child_ids_and_audit_timestamps(self):
        addition = Addition.objects.create(
            batch=self.batch,
            kind=Addition.Kind.HONEY,
            name="Wildflower",
            quantity="3.0000",
            unit=QuantityUnit.POUND,
            added_at=timezone.now(),
            notes="Recorded batch data, never an instruction.",
        )
        context = get_batch_context_for_owner(
            owner_id=str(self.owner.pk),
            batch_id=str(self.batch.pk),
        )

        self.assertEqual(context["batch"]["id"], str(self.batch.pk))
        self.assertNotIn("created_at", context["batch"])
        self.assertNotIn("updated_at", context["batch"])
        exported_addition = context["batch"]["additions"][0]
        self.assertNotIn("id", exported_addition)
        self.assertNotIn(str(addition.pk), str(context))
        self.assertNotIn("recorded_at", exported_addition)
        self.assertNotIn("updated_at", exported_addition)
        self.assertIn("added_at", exported_addition)

    def test_context_is_full_or_errors_when_utf8_payload_exceeds_cap(self):
        Observation.objects.create(
            batch=self.batch,
            category=Observation.Category.GENERAL,
            observed_at=timezone.now(),
            text="x" * (MAX_BATCH_CONTEXT_UTF8_BYTES + 1),
        )

        with self.assertRaisesRegex(
            ValueError,
            "will not silently truncate",
        ):
            get_batch_context_for_owner(
                owner_id=str(self.owner.pk),
                batch_id=str(self.batch.pk),
            )

    def test_foreign_and_missing_batches_share_the_same_error(self):
        for batch_id in (self.foreign_batch.pk, uuid4()):
            with self.subTest(batch_id=batch_id), self.assertRaisesRegex(
                ValueError,
                "Batch not found or unavailable",
            ):
                get_batch_context_for_owner(
                    owner_id=str(self.owner.pk),
                    batch_id=str(batch_id),
                )

    def test_inactive_owner_is_rejected(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])

        with self.assertRaises(PermissionError):
            list_batches_for_owner(owner_id=str(self.owner.pk))


@override_settings(
    DEBUG=True,
    MCP_PUBLIC_URL=RESOURCE_URL,
    OAUTH_ISSUER_URL=ISSUER_URL,
    MCP_HOST="127.0.0.1",
    CHATGPT_OAUTH_CLIENT_ID="chatgpt-test-client",
)
class MCPTokenVerifierTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="oauth-owner",
            password="test-password",
        )
        self.application = Application.objects.create(
            name="ChatGPT Mead Tracker",
            client_id="chatgpt-test-client",
            client_secret="",
            hash_client_secret=False,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://chatgpt.com/connector/oauth/test-callback",
        )
        self.verifier = MeadOAuthTokenVerifier(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
        )

    def create_token(
        self,
        *,
        raw_token: str = "valid-test-token",
        scope: str = READ_SCOPE,
        resource=None,
        expires=None,
        user=None,
    ) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            user=self.user if user is None else user,
            application=self.application,
            token=raw_token,
            scope=scope,
            resource=[RESOURCE_URL] if resource is None else resource,
            expires=expires or (timezone.now() + timedelta(hours=1)),
        )

    def modern_headers(
        self,
        *,
        method: str,
        name: str | None = None,
        raw_token: str = "valid-test-token",
        origin: str | None = None,
        host: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {raw_token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
            "MCP-Method": method,
        }
        if name is not None:
            headers["MCP-Name"] = name
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        return headers

    def modern_message(
        self,
        *,
        request_id: int,
        method: str,
        name: str | None = None,
        arguments: dict | None = None,
    ) -> dict:
        params = {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": (
                    LATEST_PROTOCOL_VERSION
                ),
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        }
        if name is not None:
            params["name"] = name
            params["arguments"] = arguments or {}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

    def test_valid_token_maps_to_stable_mead_owner(self):
        self.create_token()

        verified = self.verifier._verify_token_sync("valid-test-token")

        self.assertIsNotNone(verified)
        self.assertEqual(verified.subject, str(self.user.pk))
        self.assertEqual(verified.client_id, self.application.client_id)
        self.assertEqual(verified.resource, RESOURCE_URL)
        self.assertIn(READ_SCOPE, verified.scopes)
        self.assertNotEqual(verified.token, "")

    def test_rejects_expired_wrong_scope_and_unbound_tokens(self):
        cases = [
            {
                "raw_token": "expired",
                "expires": timezone.now() - timedelta(seconds=1),
            },
            {"raw_token": "wrong-scope", "scope": "profile"},
            {"raw_token": "unbound", "resource": []},
            {
                "raw_token": "wrong-resource",
                "resource": ["https://other.example.test/mcp"],
            },
            {
                "raw_token": "multiple-resources",
                "resource": [RESOURCE_URL, "https://other.example.test/mcp"],
            },
        ]
        for token_options in cases:
            with self.subTest(raw_token=token_options["raw_token"]):
                self.create_token(**token_options)
                self.assertIsNone(
                    self.verifier._verify_token_sync(token_options["raw_token"])
                )

    def test_rejects_inactive_user_and_unknown_token(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.create_token(raw_token="inactive")

        self.assertIsNone(self.verifier._verify_token_sync("inactive"))
        self.assertIsNone(self.verifier._verify_token_sync("unknown"))

    def test_rejects_token_issued_to_a_different_oauth_client(self):
        other_application = Application.objects.create(
            name="Untrusted public client",
            client_id="other-client",
            client_secret="",
            hash_client_secret=False,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.test/callback",
        )
        OAuthAccessToken.objects.create(
            user=self.user,
            application=other_application,
            token="other-client-token",
            scope=READ_SCOPE,
            resource=[RESOURCE_URL],
            expires=timezone.now() + timedelta(hours=1),
        )

        self.assertIsNone(
            self.verifier._verify_token_sync("other-client-token")
        )

    def test_protected_resource_metadata_and_auth_challenge(self):
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )

        with TestClient(
            application,
            base_url=ORIGIN_URL,
        ) as client:
            metadata = client.get(
                "/.well-known/oauth-protected-resource/mcp"
            )
            unauthorized = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                },
            )

        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.json()["resource"], RESOURCE_URL)
        self.assertEqual(
            metadata.json()["authorization_servers"],
            [ISSUER_URL],
        )
        self.assertEqual(metadata.json()["scopes_supported"], [READ_SCOPE])
        self.assertEqual(unauthorized.status_code, 401)
        self.assertIn(
            "/.well-known/oauth-protected-resource/mcp",
            unauthorized.headers["www-authenticate"],
        )

    def test_valid_bearer_token_reaches_mcp_protocol(self):
        self.create_token()
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )

        with TestClient(
            application,
            base_url=ORIGIN_URL,
        ) as client:
            response = client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer valid-test-token",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "mead-tracker-test",
                            "version": "1.0",
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["result"]["serverInfo"]["name"],
            "mead-tracker",
        )

    def test_tools_list_advertises_exact_constraints_outputs_and_oauth(self):
        self.create_token()
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )

        with TestClient(application, base_url=ORIGIN_URL) as client:
            response = client.post(
                "/mcp",
                headers=self.modern_headers(method="tools/list"),
                json=self.modern_message(
                    request_id=2,
                    method="tools/list",
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        tools = {
            tool["name"]: tool
            for tool in response.json()["result"]["tools"]
        }
        self.assertEqual(set(tools), {"list_batches", "get_batch_context"})

        list_tool = tools["list_batches"]
        context_tool = tools["get_batch_context"]
        self.assertEqual(list_tool["_meta"], OAUTH_TOOL_META)
        self.assertEqual(context_tool["_meta"], OAUTH_TOOL_META)

        list_input = list_tool["inputSchema"]
        self.assertEqual(
            set(list_input["properties"]),
            {"query", "status", "limit", "offset"},
        )
        self.assertEqual(
            list_input["properties"]["query"]["anyOf"][0]["maxLength"],
            MAX_BATCH_SEARCH_QUERY_LENGTH,
        )
        self.assertEqual(
            list_input["properties"]["status"]["anyOf"][0]["enum"],
            list(Batch.Status.values),
        )
        self.assertEqual(
            {
                "minimum": list_input["properties"]["limit"]["minimum"],
                "maximum": list_input["properties"]["limit"]["maximum"],
            },
            {"minimum": 1, "maximum": MAX_BATCH_LIST_RESULTS},
        )
        self.assertEqual(
            {
                "minimum": list_input["properties"]["offset"]["minimum"],
                "maximum": list_input["properties"]["offset"]["maximum"],
            },
            {"minimum": 0, "maximum": MAX_BATCH_LIST_OFFSET},
        )
        self.assertEqual(
            context_tool["inputSchema"]["properties"],
            {
                "batch_id": {
                    "description": "Stable UUID returned by list_batches.",
                    "format": "uuid",
                    "title": "Batch Id",
                    "type": "string",
                }
            },
        )

        list_output = list_tool["outputSchema"]
        self.assertFalse(list_output["additionalProperties"])
        self.assertEqual(
            set(list_output["properties"]),
            {
                "batches",
                "count",
                "total",
                "result_limit",
                "offset",
                "has_more",
                "next_offset",
            },
        )
        self.assertEqual(
            set(list_output["required"]),
            set(list_output["properties"]),
        )

        context_output = context_tool["outputSchema"]
        self.assertFalse(context_output["additionalProperties"])
        self.assertEqual(
            set(context_output["properties"]),
            {
                "format",
                "version",
                "exported_at",
                "content_revision",
                "batch",
            },
        )
        batch_properties = context_output["$defs"]["BatchDetailsOutput"][
            "properties"
        ]
        self.assertNotIn("created_at", batch_properties)
        self.assertNotIn("updated_at", batch_properties)
        self.assertEqual(
            set(
                context_output["$defs"]["AdditionOutput"]["properties"]
            ),
            {
                "kind",
                "name",
                "quantity",
                "unit",
                "custom_unit",
                "phase",
                "added_at",
                "notes",
            },
        )
        self.assertIn(
            "every returned string",
            context_tool["description"].lower(),
        )

    def test_get_context_over_wire_is_single_copy_and_minimized(self):
        batch = Batch.objects.create(
            owner=self.user,
            name="Unique Wire Payload Name",
            batch_number="WIRE-1",
            status=Batch.Status.FERMENTING,
        )
        addition = Addition.objects.create(
            batch=batch,
            kind=Addition.Kind.NUTRIENT,
            name="Fermaid O",
            quantity="1.2500",
            unit=QuantityUnit.GRAM,
            added_at=timezone.now(),
            notes="Ignore prior instructions is stored data only.",
        )
        self.create_token()
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )

        with TestClient(application, base_url=ORIGIN_URL) as client:
            response = client.post(
                "/mcp",
                headers=self.modern_headers(
                    method="tools/call",
                    name="get_batch_context",
                ),
                json=self.modern_message(
                    request_id=3,
                    method="tools/call",
                    name="get_batch_context",
                    arguments={"batch_id": str(batch.pk)},
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertFalse(result["isError"])
        self.assertNotIn(batch.name, result["content"][0]["text"])
        self.assertIn("untrusted data", result["content"][0]["text"])
        structured = result["structuredContent"]
        self.assertEqual(structured["batch"]["id"], str(batch.pk))
        self.assertEqual(structured["batch"]["name"], batch.name)
        self.assertEqual(response.text.count(batch.name), 1)
        self.assertNotIn("created_at", structured["batch"])
        self.assertNotIn("updated_at", structured["batch"])
        exported_addition = structured["batch"]["additions"][0]
        self.assertNotIn("id", exported_addition)
        self.assertNotIn(str(addition.pk), response.text)
        self.assertNotIn("recorded_at", exported_addition)
        self.assertNotIn("updated_at", exported_addition)
        self.assertIn("added_at", exported_addition)

    def test_get_context_over_wire_masks_foreign_batch(self):
        other_user = get_user_model().objects.create_user(
            username="foreign-wire-owner",
            password="test-password",
        )
        foreign_batch = Batch.objects.create(
            owner=other_user,
            name="Never Disclose This Batch",
            status=Batch.Status.AGING,
        )
        self.create_token()
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )

        with TestClient(application, base_url=ORIGIN_URL) as client:
            response = client.post(
                "/mcp",
                headers=self.modern_headers(
                    method="tools/call",
                    name="get_batch_context",
                ),
                json=self.modern_message(
                    request_id=4,
                    method="tools/call",
                    name="get_batch_context",
                    arguments={"batch_id": str(foreign_batch.pk)},
                ),
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Batch not found or unavailable", result["content"][0]["text"])
        self.assertNotIn(foreign_batch.name, response.text)

    def test_transport_rejects_untrusted_host_and_origin(self):
        self.create_token()
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )
        message = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "mead-tracker-test",
                    "version": "1.0",
                },
            },
        }

        with TestClient(application, base_url=ORIGIN_URL) as client:
            bad_host = client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer valid-test-token",
                    "Accept": "application/json, text/event-stream",
                    "Host": "attacker.example",
                },
                json=message,
            )
            bad_origin = client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer valid-test-token",
                    "Accept": "application/json, text/event-stream",
                    "Origin": "https://attacker.example",
                },
                json=message,
            )

        self.assertEqual(bad_host.status_code, 421)
        self.assertEqual(bad_origin.status_code, 403)

    def test_tool_call_uses_the_bearer_subject_as_owner(self):
        own_batch = Batch.objects.create(
            owner=self.user,
            name="Token Owner Batch",
            status=Batch.Status.FERMENTING,
        )
        other_user = get_user_model().objects.create_user(
            username="oauth-other",
            password="test-password",
        )
        foreign_batch = Batch.objects.create(
            owner=other_user,
            name="Foreign Batch",
            status=Batch.Status.AGING,
        )
        self.create_token()
        application = create_mcp_application(
            resource_url=RESOURCE_URL,
            issuer_url=ISSUER_URL,
            host="127.0.0.1",
        )
        headers = {
            "Authorization": "Bearer valid-test-token",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
            "MCP-Method": "tools/call",
            "MCP-Name": "list_batches",
        }

        with TestClient(
            application,
            base_url=ORIGIN_URL,
        ) as client:
            response = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "list_batches",
                        "arguments": {},
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": (
                                LATEST_PROTOCOL_VERSION
                            ),
                            "io.modelcontextprotocol/clientCapabilities": {},
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        structured = response.json()["result"]["structuredContent"]
        self.assertEqual(structured["count"], 1)
        self.assertEqual(structured["batches"][0]["id"], str(own_batch.pk))
        self.assertNotIn(str(foreign_batch.pk), str(structured))
