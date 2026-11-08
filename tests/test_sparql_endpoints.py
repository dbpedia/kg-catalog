"""
Tests for the SPARQL endpoint multi-endpoint support (issue #82).

Covers:
  - parse_sparql_endpoints() from generate_metadata.py / validate_new_kg.py
  - URL validation logic
  - publish_to_moss_http.py endpoint triple generation
  - Integration: gnd/metadata.yaml produces 3 triples (not 1)
"""
import os
import pytest
import yaml
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Helpers copied inline to avoid module-level side-effects in the scripts
# ---------------------------------------------------------------------------

def _clean_yaml(text):
    if not text:
        return text
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _parse_sparql_endpoints(text):
    if not text:
        return []
    text = text.strip()
    if not text or text == "_No response_":
        return []
    cleaned = _clean_yaml(text)
    if cleaned.startswith("-") or "\n" in cleaned:
        try:
            loaded = yaml.safe_load(cleaned)
            if isinstance(loaded, list):
                endpoints = []
                for i, item in enumerate(loaded):
                    if isinstance(item, dict):
                        endpoints.append(item)
                    elif isinstance(item, str) and item.strip():
                        name = "main" if i == 0 else f"endpoint-{i + 1}"
                        endpoints.append({"name": name, "url": item.strip()})
                if endpoints:
                    return endpoints
            elif isinstance(loaded, dict) and "url" in loaded:
                return [loaded]
        except Exception:
            pass
    raw_urls = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in line.split(","):
            u = part.strip()
            if u:
                raw_urls.append(u)
    endpoints = []
    for i, u in enumerate(raw_urls):
        name = "main" if i == 0 else f"endpoint-{i + 1}"
        endpoints.append({"name": name, "url": u})
    return endpoints


def _valid_url(value):
    if not value:
        return False
    try:
        r = urlparse(value)
        return r.scheme in ("http", "https") and bool(r.netloc)
    except Exception:
        return False


def _moss_triples(sparql):
    triples = []
    if not sparql:
        return triples
    if isinstance(sparql, str):
        triples.append(f"    void:sparqlEndpoint <{sparql}> ;")
    elif isinstance(sparql, list):
        for entry in sparql:
            if isinstance(entry, dict):
                ep_url = entry.get("url")
            elif isinstance(entry, str):
                ep_url = entry
            else:
                ep_url = None
            if ep_url:
                triples.append(f"    void:sparqlEndpoint <{ep_url}> ;")
    return triples


# ===========================================================================
# 1. parse_sparql_endpoints
# ===========================================================================

class TestParseSparqlEndpoints:

    def test_none_returns_empty(self):
        assert _parse_sparql_endpoints(None) == []

    def test_empty_string_returns_empty(self):
        assert _parse_sparql_endpoints("") == []

    def test_no_response_placeholder_returns_empty(self):
        assert _parse_sparql_endpoints("_No response_") == []

    def test_single_url(self):
        result = _parse_sparql_endpoints("https://example.org/sparql")
        assert len(result) == 1
        assert result[0]["url"] == "https://example.org/sparql"
        assert result[0]["name"] == "main"

    def test_multiline_two_urls(self):
        text = "https://a.org/sparql\nhttps://b.org/sparql"
        result = _parse_sparql_endpoints(text)
        assert len(result) == 2
        assert result[0]["name"] == "main"
        assert result[1]["name"] == "endpoint-2"
        assert result[1]["url"] == "https://b.org/sparql"

    def test_comma_separated_two_urls(self):
        text = "https://a.org/sparql, https://b.org/sparql"
        result = _parse_sparql_endpoints(text)
        assert len(result) == 2

    def test_gnd_three_endpoints_multiline(self):
        text = (
            "https://sparql.dnb.de/api/gnd\n"
            "https://sparql.dnb.de/api/dnbgnd\n"
            "https://sparql.dnb.de/api/zdb"
        )
        result = _parse_sparql_endpoints(text)
        assert len(result) == 3
        assert result[0]["url"] == "https://sparql.dnb.de/api/gnd"
        assert result[2]["url"] == "https://sparql.dnb.de/api/zdb"

    def test_yaml_list_of_dicts(self):
        text = (
            "- name: main\n"
            "  url: https://a.org/sparql\n"
            "- name: mirror\n"
            "  url: https://b.org/sparql"
        )
        result = _parse_sparql_endpoints(text)
        assert len(result) == 2
        assert result[1]["name"] == "mirror"

    def test_yaml_list_of_strings(self):
        text = "- https://a.org/sparql\n- https://b.org/sparql"
        result = _parse_sparql_endpoints(text)
        assert len(result) == 2
        assert result[0]["url"] == "https://a.org/sparql"

    def test_blank_lines_skipped(self):
        text = "\nhttps://a.org/sparql\n\nhttps://b.org/sparql\n"
        result = _parse_sparql_endpoints(text)
        assert len(result) == 2


# ===========================================================================
# 2. URL validation
# ===========================================================================

class TestValidUrl:

    def test_valid_https(self):
        assert _valid_url("https://sparql.dnb.de/api/gnd") is True

    def test_valid_http(self):
        assert _valid_url("http://dskg.org/sparql") is True

    def test_invalid_no_scheme(self):
        assert _valid_url("sparql.dnb.de/api/gnd") is False

    def test_invalid_ftp_scheme(self):
        assert _valid_url("ftp://example.org/sparql") is False

    def test_empty_string(self):
        assert _valid_url("") is False

    def test_none(self):
        assert _valid_url(None) is False


# ===========================================================================
# 3. MOSS triple generation
# ===========================================================================

class TestMossTriples:

    def test_empty_sparql_list(self):
        assert _moss_triples([]) == []

    def test_none_sparql(self):
        assert _moss_triples(None) == []

    def test_single_endpoint(self):
        sparql = [{"name": "main", "url": "https://example.org/sparql"}]
        triples = _moss_triples(sparql)
        assert len(triples) == 1
        assert "<https://example.org/sparql>" in triples[0]

    def test_multiple_endpoints_gnd(self):
        """Regression: gnd has 3 endpoints, all 3 must appear."""
        sparql = [
            {"name": "gnd",    "url": "https://sparql.dnb.de/api/gnd",    "ui": "https://sparql.dnb.de"},
            {"name": "dnbgnd", "url": "https://sparql.dnb.de/api/dnbgnd", "ui": "https://sparql.dnb.de"},
            {"name": "zdb",    "url": "https://sparql.dnb.de/api/zdb",    "ui": "https://sparql.dnb.de"},
        ]
        triples = _moss_triples(sparql)
        assert len(triples) == 3
        assert any("api/gnd" in t for t in triples)
        assert any("api/dnbgnd" in t for t in triples)
        assert any("api/zdb" in t for t in triples)

    def test_entry_missing_url_is_skipped(self):
        sparql = [{"name": "broken"}, {"name": "ok", "url": "https://example.org/sparql"}]
        triples = _moss_triples(sparql)
        assert len(triples) == 1

    def test_plain_string_sparql(self):
        triples = _moss_triples("https://example.org/sparql")
        assert len(triples) == 1

    def test_list_of_plain_strings(self):
        sparql = ["https://a.org/sparql", "https://b.org/sparql"]
        triples = _moss_triples(sparql)
        assert len(triples) == 2


# ===========================================================================
# 4. Integration: gnd/metadata.yaml produces 3 triples
# ===========================================================================

class TestGndMetadataYaml:

    @pytest.fixture
    def gnd_data(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "knowledge-graphs",
            "gnd",
            "metadata.yaml",
        )
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_gnd_has_three_sparql_entries(self, gnd_data):
        sparql = gnd_data.get("sparql", [])
        assert len(sparql) == 3

    def test_gnd_all_entries_have_valid_url(self, gnd_data):
        for entry in gnd_data["sparql"]:
            assert "url" in entry
            assert _valid_url(entry["url"])

    def test_gnd_all_endpoints_produce_triples(self, gnd_data):
        triples = _moss_triples(gnd_data["sparql"])
        assert len(triples) == 3
