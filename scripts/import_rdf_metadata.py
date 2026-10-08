"""Pull DCAT/VoID metadata into an existing KG Catalog entry."""

import argparse
import copy
import os
import re
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDF
from rdflib.util import guess_format

VOID = Namespace("http://rdfs.org/ns/void#")
# RDFLib's predefined DCAT namespace may not include the DCAT 3 version terms.
DCAT = Namespace("http://www.w3.org/ns/dcat#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
MAX_METADATA_BYTES = 20 * 1024 * 1024
RDF_FORMATS = {"turtle", "xml", "nt"}
MEDIA_TYPES = {
    "text/turtle": "ttl",
    "application/rdf+xml": "rdf",
    "application/n-triples": "nt",
    "application/n-quads": "nq",
    "application/trig": "trig",
    "application/ld+json": "jsonld",
}
COMPRESSION_TYPES = {
    "application/gzip": "gz",
    "application/x-gzip": "gz",
    "application/x-bzip2": "bz2",
    "application/x-xz": "xz",
    "application/zip": "zip",
}
LINKS = (
    DCTERMS.hasPart,
    VOID.subset,
    DCAT.hasVersion,
    DCAT.hasCurrentVersion,
    DCAT.distribution,
    DCAT.accessService,
    SPDX.checksum,
)
PROPERTIES = LINKS + (
    RDF.type,
    DCTERMS.identifier,
    DCTERMS.title,
    DCTERMS.abstract,
    DCTERMS.description,
    DCTERMS.license,
    FOAF.homepage,
    DCAT.landingPage,
    DCAT.version,
    OWL.versionInfo,
    DCAT.downloadURL,
    DCTERMS.format,
    DCAT.mediaType,
    DCAT.compressFormat,
    DCAT.byteSize,
    VOID.dataDump,
    VOID.sparqlEndpoint,
    DCAT.endpointURL,
    SPDX.algorithm,
    SPDX.checksumValue,
)


def iri(value):
    if not isinstance(value, str) or not urlparse(value).scheme:
        raise ValueError("Expected an absolute dataset IRI")
    if re.search(r'[\x00-\x20<>"{}|^`\\]', value):
        raise ValueError("Invalid characters in dataset IRI")
    node = URIRef(value)
    node.n3()  # Reject characters that would produce an invalid SPARQL IRI.
    return node


def http_url(value):
    parsed = urlparse(str(value))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Expected an HTTP(S) URL: {value}")
    iri(str(value))
    return str(value)


def construct_query(dataset):
    """Read only the selected dataset's metadata, not its instance triples."""
    root = iri(dataset).n3()
    path = "|".join(p.n3() for p in LINKS)
    properties = ", ".join(p.n3() for p in PROPERTIES)
    return (
        "CONSTRUCT { ?s ?p ?o } WHERE {\n"
        f"  {root} ({path})* ?s .\n"
        f"  ?s ?p ?o . FILTER (?p IN ({properties}))\n"
        "}"
    )


def load_graph(source, base_dir=Path(".")):
    if not isinstance(source, dict):
        raise ValueError("metadata-source must be a YAML mapping")
    locations = [key for key in ("file", "url", "sparql") if source.get(key)]
    if len(locations) != 1:
        raise ValueError("metadata-source needs exactly one of file, url or sparql")
    dataset = source.get("dataset")
    iri(dataset)
    kind = locations[0]
    rdf_format = source.get("format")
    if rdf_format is not None and rdf_format not in RDF_FORMATS:
        raise ValueError("Metadata format must be turtle, xml or nt")

    if kind == "file":
        path = base_dir / source[kind]
        if path.stat().st_size > MAX_METADATA_BYTES:
            raise ValueError("RDF metadata exceeds the 20 MiB limit")
        data = path.read_bytes()
        public_id = path.resolve().as_uri()
        rdf_format = rdf_format or guess_format(str(path))
    else:
        url = http_url(source[kind])
        params = {"query": construct_query(dataset)} if kind == "sparql" else None
        headers = {
            "Accept": "text/turtle, application/rdf+xml;q=0.9, application/n-triples;q=0.8",
            "User-Agent": "kg-catalog-metadata-importer/1.0",
        }
        with requests.get(
            url, params=params, headers=headers, timeout=30, stream=True
        ) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_METADATA_BYTES:
                    raise ValueError("RDF metadata exceeds the 20 MiB limit")
                chunks.append(chunk)
            data = b"".join(chunks)
            public_id = response.url
            content_type = (
                response.headers.get("Content-Type", "").split(";", 1)[0].strip()
            )
            rdf_format = (
                rdf_format
                or {
                    "text/turtle": "turtle",
                    "application/rdf+xml": "xml",
                    "application/n-triples": "nt",
                }.get(content_type)
                or guess_format(urlparse(public_id).path)
            )

    if rdf_format not in RDF_FORMATS:
        raise ValueError(
            "Cannot determine RDF metadata format; set metadata-source.format"
        )
    graph = Graph()
    graph.parse(data=data, format=rdf_format, publicID=public_id)
    return graph


def text(graph, node, *predicates):
    for predicate in predicates:
        values = [
            v
            for v in graph.objects(node, predicate)
            if isinstance(v, Literal) and str(v).strip()
        ]
        if values:
            values.sort(
                key=lambda v: (
                    0
                    if (v.language or "").lower().split("-")[0] == "en"
                    else 1
                    if not v.language
                    else 2,
                    str(v),
                )
            )
            return str(values[0]).strip()
    return None


def resource(graph, node, *predicates):
    for predicate in predicates:
        values = sorted(
            v for v in graph.objects(node, predicate) if isinstance(v, URIRef)
        )
        if values:
            return http_url(values[0])
    return None


def objects(graph, node, *predicates):
    return sorted({v for p in predicates for v in graph.objects(node, p)}, key=str)


def media_type(value):
    return str(value).split("/media-types/", 1)[-1].lower()


def distribution(graph, node, url):
    url = http_url(url)
    parsed = urlparse(url)
    filename = parse_qs(parsed.query).get("filename", [unquote(parsed.path)])[0]
    suffixes = Path(filename).suffixes
    compression = (
        suffixes[-1][1:].lower()
        if suffixes and suffixes[-1][1:].lower() in {"gz", "bz2", "xz", "zip"}
        else None
    )
    if compression:
        suffixes = suffixes[:-1]
    fmt = suffixes[-1][1:].lower() if suffixes else None
    if node is not None:
        for value in objects(graph, node, DCAT.mediaType, DCTERMS.format):
            declared = MEDIA_TYPES.get(media_type(value), str(value).lower())
            if declared in {"ttl", "rdf", "nt", "nq", "trig", "jsonld", "owl", "xml"}:
                fmt = declared
                break
        for value in graph.objects(node, DCAT.compressFormat):
            declared = COMPRESSION_TYPES.get(media_type(value))
            if declared:
                compression = declared
    if fmt not in {"ttl", "rdf", "nt", "nq", "trig", "jsonld", "owl", "xml"}:
        raise ValueError(f"Cannot determine the RDF dump format for {url}")
    result = {"file": url, "format": fmt, "status": "pending"}
    if compression:
        result["compression"] = compression
    if node is not None:
        size = text(graph, node, DCAT.byteSize)
        if size is not None:
            try:
                number = Decimal(size)
                if (
                    not number.is_finite()
                    or number < 0
                    or number != number.to_integral_value()
                ):
                    raise InvalidOperation
                result["size"] = int(number)
            except InvalidOperation as error:
                raise ValueError(f"Invalid dcat:byteSize for {url}") from error
        for checksum in graph.objects(node, SPDX.checksum):
            if (checksum, SPDX.algorithm, SPDX.checksumAlgorithm_sha256) in graph:
                value = text(graph, checksum, SPDX.checksumValue)
                if value is None or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                    raise ValueError(f"Invalid SHA-256 checksum for {url}")
                result["sha256"] = value.lower()
    return result


def release_distributions(graph, release):
    by_url = {}
    for node in graph.objects(release, DCAT.distribution):
        for url in graph.objects(node, DCAT.downloadURL):
            if not isinstance(url, URIRef):
                raise ValueError("dcat:downloadURL must be an IRI")
            entry = distribution(graph, node, url)
            if entry["file"] in by_url and by_url[entry["file"]] != entry:
                raise ValueError(f"Conflicting metadata for {url}")
            by_url[entry["file"]] = entry
    for url in graph.objects(release, VOID.dataDump):
        if not isinstance(url, URIRef):
            raise ValueError("void:dataDump must be an IRI")
        if str(url) not in by_url:
            by_url[str(url)] = distribution(graph, None, url)
    if not by_url:
        raise ValueError(f"No dcat:downloadURL or void:dataDump for {release}")
    return [by_url[url] for url in sorted(by_url)]


def merge_metadata(metadata, graph, dataset):
    """Keep catalog identity and historical releases; replace each observed file set."""
    root = iri(dataset)
    if not any((root, RDF.type, cls) in graph for cls in (DCAT.Dataset, VOID.Dataset)):
        raise ValueError(
            "Selected dataset is not described as dcat:Dataset or void:Dataset"
        )
    result = copy.deepcopy(metadata)
    description = text(graph, root, DCTERMS.description)
    fields = {
        "title": text(graph, root, DCTERMS.title),
        "description": description,
        "abstract": text(graph, root, DCTERMS.abstract)
        or (description[:300] if description else None),
        "license": resource(graph, root, DCTERMS.license),
        "homepage": resource(graph, root, FOAF.homepage, DCAT.landingPage),
    }
    result.update({key: value for key, value in fields.items() if value is not None})
    for key in ("databus-account", "id", "title", "description", "license", "homepage"):
        if not result.get(key):
            raise ValueError(
                f"Missing {key}: provide it in the RDF or existing catalog YAML"
            )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(result["id"])):
        raise ValueError(
            "Catalog id must contain lowercase letters, digits and hyphens"
        )
    if len(result.get("abstract", "")) > 300:
        raise ValueError("Abstract exceeds 300 characters")
    http_url(result["license"])
    http_url(result["homepage"])

    artifacts = result.setdefault("artifacts", [])
    by_id = {a["artifact"]: a for a in artifacts}
    seen = set()
    parts = objects(graph, root, DCTERMS.hasPart, VOID.subset) or [root]
    for part in parts:
        artifact_id = (
            text(graph, part, DCTERMS.identifier) if part != root else result["id"]
        )
        if not artifact_id or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", artifact_id):
            raise ValueError(
                f"Provide a stable dcterms:identifier for partition {part}"
            )
        if artifact_id in seen:
            raise ValueError(f"Duplicate artifact identifier: {artifact_id}")
        seen.add(artifact_id)
        if artifact_id not in by_id:
            by_id[artifact_id] = {"artifact": artifact_id, "versions": []}
            artifacts.append(by_id[artifact_id])
        artifact = by_id[artifact_id]
        title = text(graph, part, DCTERMS.title) or result["title"]
        desc = text(graph, part, DCTERMS.description) or result["description"]
        artifact.update(
            title=title,
            abstract=text(graph, part, DCTERMS.abstract) or desc[:300],
            description=desc,
        )
        versions = {str(v["version"]): v for v in artifact["versions"]}
        seen_versions = set()
        for release in objects(
            graph, part, DCAT.hasVersion, DCAT.hasCurrentVersion
        ) or [part]:
            label = text(graph, release, DCAT.version, OWL.versionInfo) or text(
                graph, root, DCAT.version, OWL.versionInfo
            )
            if not label or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", label):
                raise ValueError(
                    f"Missing or invalid dcat:version/owl:versionInfo for {release}"
                )
            if label in seen_versions:
                raise ValueError(f"Duplicate release label for {artifact_id}: {label}")
            seen_versions.add(label)
            incoming = release_distributions(graph, release)
            previous = versions.get(label, {})
            old_files = {d["file"]: d for d in previous.get("distributions", [])}
            distributions = []
            for entry in incoming:
                old = old_files.get(entry["file"], {})
                changed_content = any(
                    key in entry and key in old and entry[key] != old[key]
                    for key in ("sha256", "size", "format")
                ) or (bool(old) and entry.get("compression") != old.get("compression"))
                entry["status"] = (
                    "pending" if changed_content else old.get("status", "pending")
                )
                # Retain properties computed by the publisher for unchanged URLs.
                for key in ("sha256", "size"):
                    if not changed_content and key not in entry and key in old:
                        entry[key] = old[key]
                distributions.append(entry)
            release_description = text(graph, release, DCTERMS.description) or desc
            version = {
                **previous,
                "version": label,
                "title": text(graph, release, DCTERMS.title) or title,
                "abstract": text(graph, release, DCTERMS.abstract)
                or release_description[:300],
                "description": release_description,
                "license": resource(graph, release, DCTERMS.license)
                or resource(graph, part, DCTERMS.license)
                or result["license"],
                "distributions": distributions,
            }
            if label in versions:
                artifact["versions"][artifact["versions"].index(previous)] = version
            else:
                artifact["versions"].append(version)
        endpoints = objects(graph, part, VOID.sparqlEndpoint)
        for release in objects(
            graph, part, DCAT.hasVersion, DCAT.hasCurrentVersion
        ) or [part]:
            endpoints += objects(graph, release, VOID.sparqlEndpoint)
            for dist in graph.objects(release, DCAT.distribution):
                for service in graph.objects(dist, DCAT.accessService):
                    endpoints += objects(graph, service, DCAT.endpointURL)
        if part == parts[0]:
            endpoints += objects(graph, root, VOID.sparqlEndpoint)
        existing_urls = {e["url"] for e in result.get("sparql", [])}
        for endpoint in sorted(set(endpoints), key=str):
            url = http_url(endpoint)
            if url not in existing_urls:
                entries = result.setdefault("sparql", [])
                entries.append(
                    {
                        "name": "main" if not entries else f"rdf-{len(entries) + 1}",
                        "url": url,
                    }
                )
                existing_urls.add(url)
    if result != metadata:
        result["databus-publish"] = True
        result["moss-publish"] = True
    return result


def import_metadata(path, source=None, dry_run=False):
    path = Path(path)
    metadata = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("Catalog metadata must be a YAML mapping")
    source = source if source is not None else metadata.get("metadata-source")
    graph = load_graph(source, path.parent)
    updated = merge_metadata(metadata, graph, source["dataset"])
    if dry_run:
        print(yaml.safe_dump(updated, allow_unicode=True, sort_keys=False), end="")
    elif updated != metadata:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as output:
                temp_path = Path(output.name)
                yaml.safe_dump(updated, output, allow_unicode=True, sort_keys=False)
            os.chmod(temp_path, path.stat().st_mode & 0o777)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return updated != metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path, help="Existing catalog metadata.yaml")
    locations = parser.add_mutually_exclusive_group()
    for key in ("file", "url", "sparql"):
        locations.add_argument(f"--{key}")
    parser.add_argument("--dataset", help="Absolute IRI of the dataset to import")
    parser.add_argument("--format", choices=sorted(RDF_FORMATS))
    parser.add_argument(
        "--dry-run", action="store_true", help="Print proposed YAML without writing"
    )
    args = parser.parse_args()
    source = None
    chosen = next(
        (key for key in ("file", "url", "sparql") if getattr(args, key)), None
    )
    if chosen:
        if not args.dataset:
            parser.error("--dataset is required when overriding the metadata source")
        source = {chosen: getattr(args, chosen), "dataset": args.dataset}
        if args.format:
            source["format"] = args.format
    elif args.dataset or args.format:
        parser.error("--dataset/--format requires --file, --url or --sparql")
    try:
        changed = import_metadata(args.metadata, source, args.dry_run)
    except Exception as error:
        print(f"RDF metadata import failed: {error}", file=sys.stderr)
        return 1
    if not args.dry_run:
        print(f"{'Updated' if changed else 'Unchanged'}: {args.metadata}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
