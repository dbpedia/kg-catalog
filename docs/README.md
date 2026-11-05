# DBpedia KG Catalog — System documentation

This directory explains how the complete KG Catalog works across multiple repositories and services. Documentation here focuses on the **catalog as a system**, including interfaces outside the `kg-catalog` repository. Implementation-specific frontend details belong in [dbpedia/kg-catalog-web](https://github.com/dbpedia/kg-catalog-web).

| Document | For | Covers |
| --- | --- | --- |
| [Architecture](architecture.md) | All readers | System boundaries, components, data flow, ownership |
| [Metadata model](metadata-model.md) | Contributors, developers | YAML hierarchy, fields, [eight classification domains](metadata-model.md#supported-domains), publication flags |
| [Automation](automation.md) | Developers, maintainers | All six GitHub Actions workflows and their triggers |
| [Releases](releases.md) | Researchers, maintainers | Monthly metadata snapshots and release assets |
| [Operations](operations.md) | Maintainers | Credentials, checks, monitoring, failures, recovery |
| [Contribution guide](../CONTRIBUTING.md) | Contributors | Guided submissions, direct pull requests, reviews |
| [User download guide](https://kg-catalog.dbpedia.org/download.html) | KG users | Retrieving KG data using Databus tools |

## Documentation scope

- **Repository source:** `knowledge-graphs/*/metadata.yaml` — community-maintained KG descriptions.
- **Published metadata:** [DBpedia Databus](https://databus.dbpedia.org/knowledge-graph-catalog) and DBpedia MOSS.
- **Frontend:** [DBpedia KG Catalog](https://kg-catalog.dbpedia.org/) — a static website maintained in [kg-catalog-web](https://github.com/dbpedia/kg-catalog-web).
- **Snapshots:** [GitHub Releases](https://github.com/dbpedia/kg-catalog/releases) — monthly, immutable-in-practice metadata archives when published successfully.

## Maintaining this documentation

When a change modifies a YAML field, user-facing contribution path, workflow trigger, external endpoint, or release format, update the corresponding document **in the same pull request**. Prefer links to real source files over copying implementation into documentation; avoid duplicating frontend implementation details here.
