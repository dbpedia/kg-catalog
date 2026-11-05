# DBpedia Knowledge Graph Catalog

An open, community-driven catalog for discovering, describing, and reusing knowledge graphs (KGs).

**Explore the KG catalog:** https://kg-catalog.dbpedia.org/  
**Browse published KG metadata:** https://databus.dbpedia.org/knowledge-graph-catalog  
**Contribute a KG:** https://kg-catalog.dbpedia.org/submit.html

## What is the DBpedia KG Catalog?

Knowledge graphs are published by different organizations, often with metadata scattered across websites and repositories. The DBpedia KG Catalog brings descriptions of knowledge graphs, their artifacts and versions, distributions, licenses, and access information into a common catalog.

The DBpedia KG catalog is designed around three principles:

- **Community-driven contributions:** Anyone can propose new knowledge graphs or improvements to existing catalog entries.
- **Open and transparent metadata:** Source KG metadata is maintained in GitHub, with changes tracked and reviewed through pull requests.
- **Lightweight, GitHub-based architecture:** The catalog relies on GitHub for metadata management, automation, and web hosting, without requiring a dedicated application server.

The catalog describes and provides access to KG data; **it does not host the underlying KG data**. A catalog metadata release is not a dataset release.

## Start here

| I want to… | Go to… |
| --- | --- |
| Browse the KG catalog | [Catalog website](https://kg-catalog.dbpedia.org/) |
| Download catalog metadata (monthly snapshots) | [GitHub Releases](https://github.com/dbpedia/kg-catalog/releases) |
| Download KG data (individual KGs or their latest versions) | [Download guide](https://kg-catalog.dbpedia.org/download.html) |
| Register a new KG (guided form) | [New KG submission](https://github.com/dbpedia/kg-catalog/issues/new?template=new-kg-submission.yml) |
| Submit or update existing KG metadata | [Contribution guide](CONTRIBUTING.md) |
| Understand the whole system | [System architecture](docs/architecture.md) |
| Understand the KG metadata fields | [Metadata model](docs/metadata-model.md) |
| Explore the eight KG classification domains | [Supported domains](docs/metadata-model.md#supported-domains) |
| Operate the workflows | [Automation](docs/automation.md) and [Operations](docs/operations.md) |
| Understand monthly catalog snapshots | [Releases](docs/releases.md) |

## How the catalog works

1. A contributor registers a KG through a GitHub Issue form, or submits/updates YAML through a pull request.
2. Issue-form submissions are validated and, if valid, an automated pull request is prepared.
3. A maintainer reviews and merges metadata changes into `main`.
4. GitHub Actions check distribution URLs and, according to metadata publication flags, publish descriptions to **DBpedia Databus** and **DBpedia MOSS**.
5. The [catalog website](https://kg-catalog.dbpedia.org/) presents published metadata through an interactive frontend.
6. A separate scheduled workflow generates **monthly metadata snapshots** as GitHub Releases.

For actual workflow triggers, limitations, and failure behavior, see [Automation](docs/automation.md).

## How to get catalog data

- **Catalog metadata:** Download a monthly metadata snapshot (`kg-catalog-YYYY-MM.zip`) from [GitHub Releases](https://github.com/dbpedia/kg-catalog/releases). Snapshots contain source YAML and published Databus/MOSS metadata, not the underlying KG datasets. The latest source YAML is also available in [`knowledge-graphs/`](knowledge-graphs/). See [Releases](docs/releases.md) for details.
- **Knowledge graph data:** To download the actual datasets described in the catalog, follow the [download instructions on the catalog website](https://kg-catalog.dbpedia.org/download.html), which explain how to retrieve available KG versions and distributions.

## Metadata in this repository

Every catalog entry has a directory containing a `metadata.yaml` file:

```text
knowledge-graphs/
  orkg/
    metadata.yaml
  dblp/
    metadata.yaml
  ...
```

Descriptions follow this hierarchy:

```text
Knowledge graph
  └── Artifact
        └── Version
              └── Distribution (downloadable file)
```

The YAML files are the **source of truth for submitted catalog metadata**. Databus stores published KG group/artifact/version descriptions, while MOSS stores complementary KG-level metadata. Some derived values are maintained in those published systems rather than the source YAML.

See the [metadata field guide and example](docs/metadata-model.md).

## Repository layout

```text
.github/
  ISSUE_TEMPLATE/   # Guided KG submission form
  workflows/        # Validation, publication, updates, snapshots
knowledge-graphs/   # Source metadata and selected KG-specific update scripts
scripts/            # Automation, publication, export, and maintenance utilities
CONTRIBUTING.md     # How to submit and update entries
README.md           # Project overview
docs/               # System and maintainer documentation
```

## Documentation

Browse the [documentation index](docs/README.md) for the architecture, contribution lifecycle, data model, workflows, releases, downloads, and troubleshooting.

The public website's source and frontend-specific documentation are maintained separately in [dbpedia/kg-catalog-web](https://github.com/dbpedia/kg-catalog-web). Issues about catalog metadata or backend workflows belong in [this repository](https://github.com/dbpedia/kg-catalog/issues); website-specific issues belong in the [frontend issue tracker](https://github.com/dbpedia/kg-catalog-web/issues).

## Community and feedback

Contributions, corrections, and suggestions are welcome. To propose a change, read [CONTRIBUTING.md](CONTRIBUTING.md) or [open an issue](https://github.com/dbpedia/kg-catalog/issues/new/choose).

**Interested in contributing to a development issue?** We welcome new contributors and are happy to help you get started! Before commenting, please read our [Development Contribution Guidelines](CONTRIBUTING.md#contributing-to-development-issues). If you would like to work on an existing issue, please open a separate issue referencing it and briefly describe your proposed approach.

## Acknowledgement

The KG catalog is based upon work from COST Action CA23147 GOBLIN – Global Network on Large-Scale, Cross-domain and Multilingual Open Knowledge Graphs, supported by COST (European Cooperation in Science and Technology, https://www.cost.eu).
