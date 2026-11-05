# Metadata model and YAML reference

## Source of truth

Each knowledge graph has a YAML metadata record at:

```text
knowledge-graphs/<kg-id>/metadata.yaml
```

The file's top-level `id` should match `<kg-id>`. Metadata changes are reviewed through GitHub. Parts of this metadata are published into DBpedia Databus or MOSS; the systems should not be confused with the GitHub source files.

## Structural hierarchy

```text
Knowledge Graph
  └── Artifact(s): logical dataset parts, languages, modules, or subsets
        └── Version(s): releases of each artifact
              └── Distribution(s): concrete downloadable RDF file URLs
```

A KG can have several artifacts; an artifact can have several versions; a version can offer multiple file formats or compression variants.

## Top-level fields

| Field | Meaning | Notes |
| --- | --- | --- |
| `databus-account` | Databus account for publication | Catalog records normally use `knowledge-graph-catalog` |
| `id` | Unique machine-readable KG identifier | Lowercase letters, digits, hyphens for Issue-form submissions; matches directory |
| `title` | Human-readable KG name | Required by guided form |
| `abstract` | Short summary | Max 300 characters in Issue validator |
| `description` | Longer explanation | Supports plain text/Markdown-style input |
| `license` | KG license URL | Prefer canonical, resolvable license URL |
| `homepage` | KG project home page | Required by the guided Issue form |
| `domains` | One or more classification strings | Guided form asks for one primary domain |
| `keywords` | Discovery terms | Guided form requires 3–8 comma-separated keywords |
| `sparql` | Optional list of endpoint entries | Common fields: `name`, `url`, optional `ui` |
| `maintainers` | Optional contact list | Common fields: `name`, `contact`, `github` |
| `artifacts` | List of artifacts/versions/distributions | Required in guided Issue form; some older records omit it |
| `check-new-release` | Optional KG-specific update script name | Script stored beside `metadata.yaml`, executed by daily checker |
| `databus-publish` | Request a Databus publication pass | Reset to `false` by successful publisher |
| `moss-publish` | Request a MOSS KG-metadata publication pass | Reset to `false` by successful publisher |
| `last-version-size` | Optional size field used by MOSS publisher | May also be enriched in MOSS independently |

Other fields can exist in legacy or KG-specific records. This table describes **current practice**, not a fully enforced formal schema. Some existing metadata-only KG entries do not define artifacts. The repository does not currently provide a single schema for validating all YAML metadata on pull requests.

## Artifact, version, and distribution fields

| Level | Fields | Interpretation |
| --- | --- | --- |
| Artifact | `artifact`, `title`, optional `abstract`, `description` | Named logical part of a KG |
| Version | `version`, `title`, `license`, optional `abstract`, `description` | Release of one artifact |
| Distribution | `file`, `format`, optional `compression`, `status`, `sha256`, `size` | Download URL and file metadata |

`format` is a format identifier such as `ttl`, `nt`, or `rdf`; `compression` is commonly `gz`, `bz2`, or `zip`. `size` is measured in **bytes**. `sha256` is the file's hexadecimal SHA-256 checksum.

**Checksum caution:** If a distribution checksum is missing, the current Databus publisher tries to download the entire file to compute it. For multi-gigabyte dumps this is impractical. Avoid fake or placeholder checksums; agree on a verified checksum or an explicitly supported alternative before publishing large files.

### Distribution status

- `pending`: request that the publishing workflow check the URL with HTTP HEAD.
- `active`: the URL checker received HTTP 200 during a previous check, or the entry was explicitly marked active; **the current checker skips future checks** for already active entries.
- `error`: a previous attempt did not obtain HTTP 200 or encountered a request error.

These are operational flags, not proofs that a complete dataset is healthy or downloadable by every client. A successful HEAD does not verify content integrity.

## Example

```yaml
databus-account: knowledge-graph-catalog
id: example-kg
title: Example Knowledge Graph
abstract: An example of a knowledge graph catalog entry.
description: Metadata for a sample RDF dataset.
license: https://creativecommons.org/licenses/by/4.0/
homepage: https://example.org/
domains:
  - Cross-domain
keywords:
  - linked data
  - knowledge graph
  - rdf
moss-publish: true
databus-publish: true
sparql:
  - name: main
    url: https://example.org/sparql
maintainers:
  - name: Example Maintainer
    github: example-maintainer
artifacts:
  - artifact: core
    title: Core knowledge graph
    abstract: Main RDF distribution.
    versions:
      - version: 2026.10.01
        title: October 2026 edition
        license: https://creativecommons.org/licenses/by/4.0/
        distributions:
          - file: https://example.org/dumps/example.ttl.gz
            format: ttl
            compression: gz
            status: pending
            # Add real sha256 and size values when available.
```

Do not submit these example URLs as real distributions. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the submission process.

## Supported domains

The guided submission form recognizes exactly these eight primary domains.

| Domain | Scope |
| --- | --- |
| **Cross-domain** | General-purpose KGs spanning multiple domains; encyclopedic and hub datasets |
| **Geography & Environment** | Places, GIS, climate, biodiversity, earth observation, sustainability |
| **Government & Public Sector** | Public administration, law, regulations, statistics, census, public services |
| **Life Sciences & Health** | Biomedical data, clinical information, genomics, pharmaceuticals, public health |
| **Economy, Industry & Infrastructure** | Finance, companies, industry, energy, transport, logistics, infrastructure |
| **Publications, Education & Research** | Scholarly literature, bibliographic records, research data, universities, open science |
| **Media, Culture & Entertainment** | News, music, film, television, cultural heritage, museums, humanities |
| **Linguistics, Social & Digital Knowledge Systems** | Language, ontologies, social networks, software, digital/semantic infrastructure |

## How publication flags work

For newly generated issue submissions, `scripts/generate_metadata.py` sets both `databus-publish: true` and `moss-publish: true`. After successful publication, the corresponding publisher resets its flag to `false` and saves the YAML. A `false` value therefore normally indicates that publication is not currently requested, **not** that the KG does not exist in that external system.

The publication workflow runs on merges/pushes changing `knowledge-graphs/**/*.yaml` and may commit automatic status/flag changes back into the repository. See [Automation](automation.md).

## Current validation limits

- Issue-form submissions are checked by `scripts/validate_new_kg.py` for several required fields and artifact structure.
- `scripts/export_yaml_catalog.py` verifies YAML parsing and that file `id` matches directory name; it is not a full schema validator.
- `scripts/check_url_update_yaml.py` checks non-active distribution URLs using HEAD requests and can change their statuses.
- The repository does not currently include a shared JSON Schema or Pydantic model, or a dedicated pull-request validation workflow enforcing consistent requirements across all metadata records.

A shared schema and PR checks are recommended future improvements, not features that should already be claimed in user documentation.
