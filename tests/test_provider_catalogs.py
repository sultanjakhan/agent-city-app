import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import HTTPRedirectHandler

sys.path.insert(0, str(Path(__file__).parents[1]))

import provider_catalogs
from provider_catalogs import MAX_JSON, SOURCES, normalize


class FakeResponse:
    def __init__(self, body=b'{"data": []}', status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.body


class FakeOpener:
    def __init__(self, response=None):
        self.responses = response if isinstance(response, list) else [response or FakeResponse()]
        self.request = None
        self.requests = []

    def open(self, request, timeout):
        self.request = (request, timeout)
        self.requests.append((request, timeout))
        return self.responses.pop(0)


class ProviderCatalogTests(unittest.TestCase):
  def test_sources_have_fixed_catalog_contract(self):
    self.assertEqual(set(SOURCES), {"gemini", "groq", "cerebras", "mistral", "siliconflow", "huggingface"})
    self.assertFalse(SOURCES["cerebras"]["accountCatalog"])
    for source in SOURCES.values():
        self.assertTrue(source["url"].startswith("https://"))
        self.assertIn(source["auth"], {"bearer", "google"})
        self.assertTrue(source["keyUrl"].startswith("https://"))
        self.assertTrue("бесплат" in source["terms"] or "free" in source["terms"].lower())

  def test_gemini_filters_methods_and_strips_models_prefix(self):
    result = normalize("gemini", {"models": [
        {"name": "models/gemini-2.5-flash", "displayName": "Gemini Flash",
         "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    ]})
    self.assertEqual(result["models"][0]["id"], "gemini-2.5-flash")
    self.assertEqual(result["models"][0]["developer"], "google")
    self.assertFalse(result["models"][0]["priceVerified"])
    self.assertEqual(result["skippedCount"], 1)

  def test_openai_catalogs_filter_non_chat_and_keep_schema(self):
    payload = {"data": [
        {"id": "qwen/Qwen3-32B", "owned_by": "qwen", "context_length": 32768,
         "supported_parameters": ["tools"]},
        {"id": "BAAI/bge-m3", "owned_by": "BAAI"},
    ]}
    result = normalize("siliconflow", payload)
    model = result["models"][0]
    self.assertEqual(model, {"id": "qwen/Qwen3-32B", "name": "qwen/Qwen3-32B", "developer": "qwen",
                     "chinese": True, "context": 32768, "tools": True, "vision": False,
                     "priceVerified": False, "kind": "chat"})
    self.assertEqual(result["skippedCount"], 1)

  def test_mistral_requires_explicit_chat_capability(self):
    result = normalize("mistral", {"data": [
        {"id": "mistral-small-latest", "capabilities": {"completion_chat": True}, "max_context_length": 8192},
        {"id": "mistral-embed", "capabilities": {"completion_chat": False}},
        {"id": "unknown", "capabilities": {}},
    ]})
    self.assertEqual([m["id"] for m in result["models"]], ["mistral-small-latest"])
    self.assertEqual(result["skippedCount"], 2)

  def test_missing_key_does_not_open_network(self):
    with patch.object(provider_catalogs, "build_opener", side_effect=AssertionError("network")):
      with self.assertRaisesRegex(ValueError, "key"):
        provider_catalogs.fetch("groq", lambda _provider: None)

  def test_bearer_auth_is_header_and_not_query_parameter(self):
    opener = FakeOpener()
    with patch.object(provider_catalogs, "build_opener", return_value=opener):
      provider_catalogs.fetch("groq", lambda _provider: "secret")
    request, timeout = opener.request
    self.assertEqual(timeout, 15)
    self.assertEqual(request.get_header("Authorization"), "Bearer secret")
    self.assertNotIn("secret", request.full_url)

  def test_cerebras_public_catalog_never_reads_key(self):
    opener = FakeOpener()
    def fail(_provider):
      raise AssertionError("key reader called")
    with patch.object(provider_catalogs, "build_opener", return_value=opener):
      provider_catalogs.fetch("cerebras", fail)
    request, _timeout = opener.request
    self.assertIsNone(request.get_header("Authorization"))

  def test_gemini_fetches_two_pages_with_encoded_token_and_merges(self):
    opener = FakeOpener([
      FakeResponse(b'{"models":[{"name":"models/gemini-a","supportedGenerationMethods":["generateContent"]}],"nextPageToken":"a/b+c"}'),
      FakeResponse(b'{"models":[{"name":"models/gemini-b","supportedGenerationMethods":["generateContent"]}]}'),
    ])
    with patch.object(provider_catalogs, "build_opener", return_value=opener):
      result = provider_catalogs.fetch("gemini", lambda _provider: "google-secret")
    self.assertEqual([m["id"] for m in result["models"]], ["gemini-a", "gemini-b"])
    first, second = opener.requests
    self.assertIn("pageSize=1000", first[0].full_url)
    self.assertIn("pageToken=a%2Fb%2Bc", second[0].full_url)
    self.assertNotIn("google-secret", second[0].full_url)
    self.assertEqual(second[0].get_header("X-goog-api-key"), "google-secret")

  def test_gemini_repeated_token_fails(self):
    body = b'{"models":[],"nextPageToken":"same"}'
    opener = FakeOpener([FakeResponse(body), FakeResponse(body)])
    with patch.object(provider_catalogs, "build_opener", return_value=opener):
      with self.assertRaisesRegex(ValueError, "token"):
        provider_catalogs.fetch("gemini", {"gemini": "secret"})

  def test_gemini_page_limit_fails(self):
    bodies = [FakeResponse((f'{{"models":[],"nextPageToken":"next{i}"}}').encode()) for i in range(5)]
    opener = FakeOpener(bodies)
    with patch.object(provider_catalogs, "build_opener", return_value=opener):
      with self.assertRaisesRegex(ValueError, "limit"):
        provider_catalogs.fetch("gemini", {"gemini": "secret"})

  def test_cerebras_family_beats_platform_owner(self):
    result = normalize("cerebras", {"data": [
      {"id": "qwen-3-235b-a22b-instruct-2507", "owned_by": "Cerebras"},
      {"id": "zai-glm-4.7", "owned_by": "Cerebras"},
    ]})
    self.assertEqual([m["developer"] for m in result["models"]], ["qwen", "zai"])

  def test_non_finite_context_is_not_exposed(self):
    result = normalize("groq", {"data": [{"id": "model", "context_length": float("inf")} ]})
    self.assertIsNone(result["models"][0]["context"])

  def test_siliconflow_image_only_models_are_skipped(self):
    result = normalize("siliconflow", {"data": [
      {"id": "Qwen/Qwen3-32B"}, {"id": "black-forest-labs/FLUX.1-dev"},
      {"id": "stabilityai/stable-diffusion-xl"},
    ]})
    self.assertEqual([m["id"] for m in result["models"]], ["Qwen/Qwen3-32B"])
    self.assertEqual(result["skippedCount"], 2)

  def test_redirect_handler_is_installed(self):
    opener = FakeOpener()
    with patch.object(provider_catalogs, "build_opener", return_value=opener) as build:
      provider_catalogs.fetch("groq", {"groq": "secret"})
    handler = build.call_args.args[0]
    self.assertIsInstance(handler, HTTPRedirectHandler)
    self.assertEqual(handler.__class__.__name__, "_NoRedirect")

  def test_oversized_response_is_rejected(self):
    opener = FakeOpener(FakeResponse(b"{" + b"x" * MAX_JSON + b"}"))
    with patch.object(provider_catalogs, "build_opener", return_value=opener):
      with self.assertRaisesRegex(ValueError, "too large"):
        provider_catalogs.fetch("groq", {"groq": "secret"})

  def test_gemini_malformed_models_field_is_rejected(self):
    with self.assertRaisesRegex(ValueError, "model list"):
      normalize("gemini", {"models": {"bad": True}})

  def test_gemini_pagination_is_not_reported_as_complete(self):
    with self.assertRaisesRegex(ValueError, "paginated"):
      normalize("gemini", {"models": [], "nextPageToken": "next"})
