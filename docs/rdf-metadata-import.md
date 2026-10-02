# Importing provider-published RDF metadata

KG providers can publish a small RDF metadata document at a fixed HTTP(S) URL,
or expose the same description through a SPARQL endpoint. The importer reads
that description and updates the catalog's existing `metadata.yaml`. It does
not download the KG dumps or publish directly to Databus/MOSS.

Install the optional import dependencies:

```bash
python -m pip install -r requirements-rdf-import.txt
```

## Source configuration

Add an opt-in `metadata-source` mapping to a catalog entry:

```yaml
metadata-source:
  url: https://example.org/metadata.ttl
  format: turtle
  dataset: https://example.org/metadata/kg
```

For a SPARQL endpoint, use `sparql` instead of `url`:

```yaml
metadata-source:
  sparql: https://example.org/sparql
  dataset: https://example.org/metadata/kg
```

Exactly one of `url`, `sparql`, or `file` is required, along with the absolute
IRI of the dataset to import. A local `file` path is resolved relative to the
catalog entry's `metadata.yaml`. Metadata serializations supported are Turtle
(`turtle`), RDF/XML (`xml`), and N-Triples (`nt`). HTTP content type or the file
extension selects the parser; set `format` explicitly if neither identifies it.
Responses are limited to 20 MiB, and HTTP requests use a 30-second timeout.

```bash
python scripts/import_rdf_metadata.py knowledge-graphs/my-kg/metadata.yaml --dry-run
python scripts/import_rdf_metadata.py knowledge-graphs/my-kg/metadata.yaml
```

`--dry-run` prints the proposed YAML without writing it. For a one-off import,
override the configured location with `--url`, `--sparql`, or `--file`, followed
by `--dataset` and optionally `--format`; these overrides are not saved.

The daily release checker automatically processes entries with
`metadata-source`. This replaces their `check-new-release` hook; other entries
keep using their existing hooks. Changed entries set `databus-publish` and
`moss-publish` so the existing publishing workflow can process them.

## RDF contract and YAML mapping

Use [DCAT 3](https://www.w3.org/TR/vocab-dcat-3/) for new descriptions. Existing
[VoID](https://www.w3.org/TR/void/) descriptions can supply subsets, direct dump
links, and SPARQL endpoint URLs. The selected dataset must explicitly have type
`dcat:Dataset` or `void:Dataset`.

| RDF property | Catalog YAML field / behavior |
| --- | --- |
| `dcterms:title` | `title`; English text is preferred, then untagged text |
| `dcterms:description` | `description` and fallback `abstract` (first 300 characters) |
| `dcterms:abstract` | `abstract` (at most 300 characters) |
| `dcterms:license` | HTTP(S) `license`; inherited from partition/root when absent on a release |
| `foaf:homepage` or `dcat:landingPage` | HTTP(S) `homepage` |
| `dcterms:hasPart` or `void:subset` | Direct partitions become separate `artifacts` |
| Partition `dcterms:identifier` | Stable artifact ID, using lowercase letters, digits, and hyphens |
| `dcat:hasVersion` or `dcat:hasCurrentVersion` | Links a partition to its release descriptions |
| `dcat:version` or `owl:versionInfo` | `version`; a root label can be inherited by partitions |
| `dcat:distribution` / `dcat:downloadURL` | A distribution's `file` URL |
| `void:dataDump` | A distribution's `file` URL, directly on the release/partition |
| `dcat:mediaType` or `dcterms:format` | `format`; otherwise inferred from the dump filename |
| `dcat:compressFormat` or compressed filename suffix | `compression` (`gz`, `bz2`, `xz`, or `zip`) |
| `dcat:byteSize` | Optional nonnegative integral byte `size` |
| `spdx:checksum` with SHA-256 algorithm | Optional `sha256` |
| `void:sparqlEndpoint` or a distribution's `dcat:accessService` / `dcat:endpointURL` | Added to `sparql` without removing locally configured endpoints |

Keep the catalog-specific `id`, `databus-account`, `domains`, `keywords`, and
`maintainers` in the YAML entry; the importer preserves them. Root title,
description, license, and homepage may come from the RDF or existing YAML.
Partition titles/descriptions inherit the root text when absent. With no direct
partitions, the root becomes one artifact using the existing catalog `id`.
With no explicit version links, each partition/root describes one release.

Every imported release needs an explicit version label and at least one direct
HTTP(S) dump URL. Labels use letters, digits, dots, underscores, and hyphens.
Dump formats supported are `ttl`, `rdf`, `xml`, `owl`, `nt`, `nq`, `trig`, and
`jsonld`. For URLs without a filename extension, declare the format on a DCAT
distribution. The `filename` query parameter is also recognized for file URLs.
The metadata parser itself does not follow JSON-LD contexts.

See [the complete RDF example](examples/kg-metadata.ttl) for two partitions,
multiple dump files, compression, byte size, and an optional checksum. Its
dataset IRI is `https://example.org/metadata/kg`.

## Release history and failure behavior

The importer adds new artifacts/releases and preserves historical versions,
including artifacts no longer present in a provider's current description.
For a release present in the RDF, its file list replaces that release's file
list in YAML: files may be added or removed between releases. Existing file
statuses and computed checksums/sizes are retained for unchanged URLs.
If the provider changes the checksum, size, format, or compression of an
existing URL, its status returns to `pending` and obsolete computed properties
are not carried forward.
Repeating an unchanged import does not rewrite YAML or reset publish flags.

A SPARQL source receives a read-only `CONSTRUCT` query scoped to the selected
dataset and its partition/version/distribution/service/checksum links, with
only the documented metadata predicates requested. Unrelated instance data is
not imported. Metadata in named graphs must also be available in the endpoint's
default graph for this query.

Invalid RDF, a missing dataset/version, conflicting artifact identifiers, or a
release without dump URLs fails the import before any YAML is written. A failed
entry is logged by the daily checker; other entries can still be checked.
`dcat:accessURL` is not treated as a downloadable dump. Access-only
distributions are ignored when other distributions provide direct dumps.

For example, the UniProt discussion in
[issue #61](https://github.com/dbpedia/kg-catalog/issues/61) confirms that its
SPARQL service description does not currently advertise RDF dump links. A
service description alone cannot create download URLs: a provider must publish
them in the RDF metadata. No file names or release labels are invented.

## Tests

The tests use local RDF, a local HTTP server, and mocked HTTP responses; they do
not crawl public endpoints, download dumps, or invoke publishing:

```bash
python -m unittest discover -s tests -v
```
