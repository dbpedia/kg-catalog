import copy
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests
import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import daily_check  # noqa: E402
import import_rdf_metadata as importer  # noqa: E402

DCAT = importer.DCAT
EX = Namespace("https://example.org/metadata/")
DATASET = str(EX.kg)
FIXTURE = ROOT / "docs" / "examples" / "kg-metadata.ttl"


class RdfMetadataImportTests(unittest.TestCase):
    def setUp(self):
        self.graph = Graph().parse(FIXTURE, format="turtle")
        self.metadata = {
            "databus-account": "knowledge-graph-catalog",
            "id": "example-kg",
            "title": "Local title",
            "description": "Local description",
            "abstract": "Local abstract",
            "license": "https://example.org/license",
            "homepage": "https://example.org",
            "domains": ["Cross-domain"],
            "keywords": ["rdf", "example", "knowledge graph"],
            "maintainers": [{"name": "Example maintainer", "github": "example"}],
            "databus-publish": False,
            "moss-publish": False,
            "artifacts": [],
        }

    def merge(self, metadata=None, graph=None):
        return importer.merge_metadata(
            self.metadata if metadata is None else metadata,
            self.graph if graph is None else graph,
            DATASET,
        )

    def core(self, metadata):
        return next(a for a in metadata["artifacts"] if a["artifact"] == "core")

    def response(self, graph=None, rdf_format="turtle", content_type="text/turtle"):
        response = Mock()
        graph = self.graph if graph is None else graph
        response.iter_content.return_value = [
            graph.serialize(format=rdf_format).encode()
        ]
        response.headers = {"Content-Type": content_type}
        response.url = "https://example.org/metadata.ttl"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context, response

    def test_imports_dcat_and_void_partitions_and_preserves_local_fields(self):
        original = copy.deepcopy(self.metadata)
        merged = self.merge()
        self.assertEqual(self.metadata, original)
        for field in ("id", "databus-account", "domains", "keywords", "maintainers"):
            self.assertEqual(merged[field], original[field])
        self.assertEqual(merged["title"], "Example Knowledge Graph")
        self.assertEqual(
            [a["artifact"] for a in merged["artifacts"]], ["core", "labels"]
        )
        files = self.core(merged)["versions"][0]["distributions"]
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["format"], "ttl")
        self.assertEqual(files[0]["compression"], "gz")
        self.assertEqual(files[0]["size"], 1234)
        self.assertEqual(files[0]["sha256"], "a" * 64)
        labels = merged["artifacts"][1]["versions"][0]["distributions"]
        self.assertEqual(
            [(d["format"], d["compression"]) for d in labels], [("nt", "bz2")] * 2
        )
        self.assertEqual(
            merged["sparql"], [{"name": "main", "url": "https://example.org/sparql"}]
        )
        self.assertTrue(merged["databus-publish"])
        self.assertTrue(merged["moss-publish"])

    def test_repeated_import_keeps_checksums_statuses_and_publish_flags(self):
        merged = self.merge()
        merged["databus-publish"] = merged["moss-publish"] = False
        for artifact in merged["artifacts"]:
            for dist in artifact["versions"][0]["distributions"]:
                dist.update(
                    status="active",
                    size=dist.get("size", 789),
                    sha256=dist.get("sha256", "b" * 64),
                )
        self.assertEqual(self.merge(merged), merged)

    def test_new_release_allows_changed_files_and_preserves_history(self):
        old = self.merge()
        self.graph.set((EX.kg, DCAT.version, Literal("2026.10.01")))
        self.graph.remove((EX.core, DCAT.distribution, EX["core-file-2"]))
        self.graph.set(
            (
                EX["core-file-1"],
                DCAT.downloadURL,
                URIRef("https://example.org/new/core-1.ttl.xz"),
            )
        )
        merged = self.merge(old)
        versions = self.core(merged)["versions"]
        self.assertEqual([v["version"] for v in versions], ["2026.09.24", "2026.10.01"])
        self.assertEqual(len(versions[0]["distributions"]), 2)
        self.assertEqual(len(versions[1]["distributions"]), 1)
        self.assertEqual(versions[1]["distributions"][0]["compression"], "xz")

    def test_observed_release_replaces_file_list_but_keeps_missing_artifacts(self):
        old = self.merge()
        self.graph.remove((EX.core, DCAT.distribution, EX["core-file-2"]))
        self.graph.remove((EX.kg, DCTERMS.hasPart, EX.labels))
        merged = self.merge(old)
        self.assertEqual(len(self.core(merged)["versions"][0]["distributions"]), 1)
        self.assertEqual(merged["artifacts"][1], old["artifacts"][1])

    def test_changed_checksum_invalidates_cached_size_and_active_status(self):
        old = self.merge()
        dist = self.core(old)["versions"][0]["distributions"][0]
        dist["status"] = "active"
        self.graph.remove((EX["core-file-1"], DCAT.byteSize, None))
        checksum = next(self.graph.objects(EX["core-file-1"], importer.SPDX.checksum))
        self.graph.set((checksum, importer.SPDX.checksumValue, Literal("c" * 64)))
        updated = self.core(self.merge(old))["versions"][0]["distributions"][0]
        self.assertEqual(updated["status"], "pending")
        self.assertEqual(updated["sha256"], "c" * 64)
        self.assertNotIn("size", updated)

    def test_explicit_multiple_versions_and_distribution_services(self):
        self.graph.remove((EX.core, DCAT.distribution, None))
        for label in ("2026.01", "2026.02"):
            release = EX[f"core-{label}"]
            self.graph.add((EX.core, DCAT.hasVersion, release))
            self.graph.add((release, DCAT.version, Literal(label)))
            self.graph.add((release, DCAT.distribution, EX["core-file-1"]))
        self.graph.add((EX["core-file-1"], DCAT.accessService, EX.service))
        self.graph.add(
            (EX.service, DCAT.endpointURL, URIRef("https://example.org/other-sparql"))
        )
        merged = self.merge()
        self.assertEqual(
            [v["version"] for v in self.core(merged)["versions"]],
            ["2026.01", "2026.02"],
        )
        self.assertIn(
            "https://example.org/other-sparql", [e["url"] for e in merged["sparql"]]
        )

    def test_single_void_dataset_and_owl_version_info(self):
        graph = Graph().parse(
            data="""
            @prefix void: <http://rdfs.org/ns/void#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            <https://example.org/metadata/kg> a void:Dataset ;
              owl:versionInfo "2026-03" ;
              void:dataDump <https://example.org/uniprotkb_1.rdf.xz>,
                            <https://example.org/uniprotkb_2.rdf.xz> .
        """,
            format="turtle",
        )
        merged = self.merge(graph=graph)
        self.assertEqual(merged["artifacts"][0]["artifact"], "example-kg")
        files = merged["artifacts"][0]["versions"][0]["distributions"]
        self.assertEqual(
            [(d["format"], d["compression"]) for d in files], [("rdf", "xz")] * 2
        )

    def test_language_selection_is_deterministic(self):
        self.graph.add((EX.kg, DCTERMS.title, Literal("Un titre", lang="fr")))
        self.assertEqual(self.merge()["title"], "Example Knowledge Graph")

    def test_access_only_distribution_is_not_a_download_url(self):
        self.graph.add((EX.core, DCAT.distribution, EX.webpage))
        self.graph.add(
            (EX.webpage, DCAT.accessURL, URIRef("https://example.org/browser"))
        )
        self.assertEqual(
            len(self.core(self.merge())["versions"][0]["distributions"]), 2
        )
        self.graph.remove((EX.core, DCAT.distribution, EX["core-file-1"]))
        self.graph.remove((EX.core, DCAT.distribution, EX["core-file-2"]))
        with self.assertRaisesRegex(ValueError, "No dcat:downloadURL or void:dataDump"):
            self.merge()

    def test_missing_version_and_partition_identifier_are_errors(self):
        self.graph.remove((EX.kg, DCAT.version, None))
        with self.assertRaisesRegex(ValueError, "versionInfo"):
            self.merge()
        self.graph.set((EX.kg, DCAT.version, Literal("2026.09.24")))
        self.graph.remove((EX.core, DCTERMS.identifier, None))
        with self.assertRaisesRegex(ValueError, "stable dcterms:identifier"):
            self.merge()

    def test_duplicate_artifact_ids_and_release_labels_are_errors(self):
        self.graph.set((EX.labels, DCTERMS.identifier, Literal("core")))
        with self.assertRaisesRegex(ValueError, "Duplicate artifact identifier"):
            self.merge()
        self.graph.set((EX.labels, DCTERMS.identifier, Literal("labels")))
        for node in (EX.v1, EX.v2):
            self.graph.add((EX.core, DCAT.hasVersion, node))
            self.graph.add((node, DCAT.version, Literal("2026.09.24")))
            self.graph.add((node, DCAT.distribution, EX["core-file-1"]))
        with self.assertRaisesRegex(ValueError, "Duplicate release label"):
            self.merge()

    def test_invalid_size_checksum_and_download_url_are_rejected(self):
        for size in ("-1", "1.5", "NaN", "not-a-number"):
            with self.subTest(size=size):
                self.graph.set((EX["core-file-1"], DCAT.byteSize, Literal(size)))
                with self.assertRaisesRegex(ValueError, "byteSize"):
                    self.merge()
        self.graph.remove((EX["core-file-1"], DCAT.byteSize, None))
        checksum = next(self.graph.objects(EX["core-file-1"], importer.SPDX.checksum))
        self.graph.set((checksum, importer.SPDX.checksumValue, Literal("bad")))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.merge()
        self.graph.remove((EX["core-file-1"], importer.SPDX.checksum, None))
        self.graph.set(
            (
                EX["core-file-1"],
                DCAT.downloadURL,
                Literal("https://example.org/dump.ttl"),
            )
        )
        with self.assertRaisesRegex(ValueError, "must be an IRI"):
            self.merge()

    def test_url_without_extension_uses_declared_media_type(self):
        self.graph.set(
            (
                EX["core-file-1"],
                DCAT.downloadURL,
                URIRef("https://example.org/download?id=1"),
            )
        )
        self.graph.add(
            (
                EX["core-file-1"],
                DCAT.compressFormat,
                URIRef("https://www.iana.org/assignments/media-types/application/gzip"),
            )
        )
        entry = self.core(self.merge())["versions"][0]["distributions"][1]
        self.assertEqual((entry["format"], entry["compression"]), ("ttl", "gz"))

    def test_dataset_scoped_construct_executes_without_instance_data(self):
        self.graph.add((EX.unrelated, RDF.type, DCAT.Dataset))
        self.graph.add((EX.unrelated, DCTERMS.title, Literal("Unrelated")))
        self.graph.add((EX.kg, EX.instanceData, Literal("Do not retrieve")))
        constructed = self.graph.query(importer.construct_query(DATASET)).graph
        self.assertFalse(list(constructed.triples((EX.unrelated, None, None))))
        self.assertNotIn((EX.kg, EX.instanceData, None), constructed)
        self.assertEqual(self.merge(graph=constructed), self.merge())
        with self.assertRaisesRegex(ValueError, "Invalid characters"):
            importer.construct_query("https://example.org/> } UNION { ?s ?p ?o")

    def test_file_url_and_sparql_read_equivalent_rdf(self):
        local = importer.load_graph({"file": str(FIXTURE), "dataset": DATASET})
        for kind, rdf_format, content_type in (
            ("url", "xml", "application/rdf+xml"),
            ("sparql", "turtle", "text/turtle"),
        ):
            with self.subTest(kind=kind):
                context, response = self.response(
                    rdf_format=rdf_format, content_type=content_type
                )
                with patch.object(
                    importer.requests, "get", return_value=context
                ) as get:
                    loaded = importer.load_graph(
                        {kind: "https://example.org/metadata", "dataset": DATASET}
                    )
                self.assertEqual(self.merge(graph=loaded), self.merge(graph=local))
                response.raise_for_status.assert_called_once()
                if kind == "sparql":
                    query = get.call_args.kwargs["params"]["query"]
                    self.assertEqual(
                        self.merge(graph=self.graph.query(query).graph), self.merge()
                    )
                else:
                    self.assertIsNone(get.call_args.kwargs["params"])

    def test_real_http_file_and_sparql_requests(self):
        graph = self.graph

        class MetadataHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query).get("query")
                result = graph.query(query[0]).graph if query else graph
                data = result.serialize(format="xml").encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/rdf+xml")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MetadataHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/metadata"
            for kind in ("url", "sparql"):
                loaded = importer.load_graph({kind: url, "dataset": DATASET})
                self.assertEqual(self.merge(graph=loaded), self.merge())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_local_xml_and_ntriples_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for rdf_format, extension in (("xml", "rdf"), ("nt", "nt")):
                path = Path(directory) / f"metadata.{extension}"
                self.graph.serialize(
                    destination=path, format=rdf_format, encoding="utf-8"
                )
                graph = importer.load_graph(
                    {"file": path.name, "dataset": DATASET}, path.parent
                )
                self.assertEqual(self.merge(graph=graph), self.merge())

    def test_source_selection_response_limits_and_http_errors(self):
        for source in (
            None,
            {},
            {
                "url": "https://example.org/a",
                "sparql": "https://example.org/b",
                "dataset": DATASET,
            },
            {"url": "file:///etc/passwd", "dataset": DATASET},
            {"file": str(FIXTURE), "dataset": DATASET, "format": "json-ld"},
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                importer.load_graph(source)
        context, response = self.response()
        response.iter_content.return_value = [b"x" * 11]
        with (
            patch.object(importer.requests, "get", return_value=context),
            patch.object(importer, "MAX_METADATA_BYTES", 10),
        ):
            with self.assertRaisesRegex(ValueError, "limit"):
                importer.load_graph(
                    {"url": "https://example.org/meta", "dataset": DATASET}
                )
        response.raise_for_status.side_effect = requests.HTTPError("Server failed")
        with patch.object(importer.requests, "get", return_value=context):
            with self.assertRaises(requests.HTTPError):
                importer.load_graph(
                    {"url": "https://example.org/meta", "dataset": DATASET}
                )

    def test_cli_dry_run_import_idempotence_and_failed_import_leave_files_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.yaml"
            self.metadata["metadata-source"] = {
                "file": str(FIXTURE),
                "dataset": DATASET,
            }
            path.write_text(yaml.safe_dump(self.metadata))
            original = path.read_bytes()
            command = [
                sys.executable,
                str(ROOT / "scripts/import_rdf_metadata.py"),
                str(path),
            ]
            dry_run = subprocess.run(
                command + ["--dry-run"], capture_output=True, text=True
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(yaml.safe_load(dry_run.stdout)["artifacts"]), 2)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = path.read_bytes()
            with patch.object(importer.os, "replace") as replace:
                self.assertFalse(importer.import_metadata(path))
                replace.assert_not_called()
            path_source = yaml.safe_load(saved)
            path_source["metadata-source"]["dataset"] = "https://example.org/missing"
            path.write_text(yaml.safe_dump(path_source))
            before = path.read_bytes()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Selected dataset", result.stderr)
            self.assertEqual(path.read_bytes(), before)

    def test_daily_checker_uses_importer_and_keeps_legacy_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, config in (
                (
                    "rdf",
                    {"metadata-source": {"url": "https://example.org/metadata.ttl"}},
                ),
                ("legacy", {"check-new-release": "check.py"}),
            ):
                (root / name).mkdir()
                (root / name / "metadata.yaml").write_text(yaml.safe_dump(config))
                (root / name / "check.py").write_text("")
            with (
                patch.object(daily_check, "KGS_ROOT", str(root)),
                patch.object(daily_check.subprocess, "run") as run,
                patch.object(daily_check, "log"),
            ):
                daily_check.run_daily_check()
            calls = [call.args[0] for call in run.call_args_list]
            self.assertEqual(len(calls), 2)
            self.assertIn(
                [
                    "python3",
                    str(ROOT / "scripts/import_rdf_metadata.py"),
                    str(root / "rdf/metadata.yaml"),
                ],
                calls,
            )
            self.assertIn(["python3", str(root / "legacy/check.py")], calls)


if __name__ == "__main__":
    unittest.main()
