# Contributing to the DBpedia KG Catalog

Thank you for helping make knowledge graphs more discoverable and reusable. We welcome both new and experienced contributors. Contributions may add a KG, correct metadata, or improve the catalog's scripts and documentation. If you want to implement an existing feature or development issue, see [Contributing to development issues](#contributing-to-development-issues).

## Option 1 — Submit a KG through the guided form

This is the easiest route for people who do not want to edit GitHub repository files directly.

1. Open the [New KG form](https://github.com/dbpedia/kg-catalog/issues/new?template=new-kg-submission.yml).
2. Complete the required fields, including the KG description, one of the [eight classification domains](docs/metadata-model.md#supported-domains), and the YAML list of artifacts, versions, and distributions.
3. Submit the issue. The `Validate New KG Submission` workflow runs automatically for issues labeled `new-kg`.
4. If validation reports errors in an issue comment, edit the issue and save it; the workflow runs again.
5. After successful validation, GitHub Actions generates `knowledge-graphs/<id>/metadata.yaml` and prepares a pull request for maintainer review.
6. A maintainer reviews the pull request and merges it when ready. Publication runs separately after the metadata reaches `main`.

**Please do not put passwords, tokens, or other secrets in issues or metadata.** Publication can depend on external systems and is not instantaneous.

## Option 2 — Submit or edit YAML through a pull request

Use this route for existing KG metadata corrections, larger changes, and contributors comfortable with Git.

1. Fork [dbpedia/kg-catalog](https://github.com/dbpedia/kg-catalog) and clone your fork.
2. For a new entry, create `knowledge-graphs/<kg-id>/metadata.yaml`, where the directory and `id` in the file are identical. For an update, edit the existing file.
3. Follow the [metadata model](docs/metadata-model.md); look at existing files for real examples.
4. Check YAML syntax and ID consistency locally:

   ```bash
   python3 -m pip install 'PyYAML>=6,<7'
   python3 scripts/export_yaml_catalog.py --repo . --output /tmp/kg-catalog-source-check --no-zip
   ```

5. Commit your changes and open a pull request against `dbpedia/kg-catalog:main`.
6. Explain the reason for the change, the KG affected, and whether it should trigger Databus and/or MOSS publication.


## Example: a minimal new entry

This is illustrative metadata, not a real KG. Replace URLs and descriptions before submitting.

```yaml
databus-account: knowledge-graph-catalog
id: example-kg
title: Example Knowledge Graph
abstract: An example RDF knowledge graph for documentation.
description: Example metadata showing the catalog hierarchy.
license: https://creativecommons.org/licenses/by/4.0/
homepage: https://example.org/
domains:
  - Cross-domain
keywords:
  - rdf
  - linked data
  - example
moss-publish: true
databus-publish: true
artifacts:
  - artifact: core
    title: Main RDF dataset
    abstract: Core example data.
    versions:
      - version: 2026.10.01
        title: Main RDF dataset — October 2026
        license: https://creativecommons.org/licenses/by/4.0/
        distributions:
          - file: https://example.org/data/core.ttl.gz
            format: ttl
            compression: gz
            status: pending
```

For an actual contribution, provide accurate download URLs, and preferably `sha256` and `size` (in bytes) for each distribution. Do not invent checksums or use placeholder values. Missing checksums may cause the Databus publisher to download the whole file, which can be extremely expensive for large KG dumps.

## Updating an existing KG

- Modify the existing YAML rather than creating a duplicate KG ID.
- Update `databus-publish: true` when changed group, artifact, version, or distribution metadata needs republishing to Databus.
- Update `moss-publish: true` when changed KG-level metadata needs republishing to MOSS.
- When providing a new or changed distribution URL, set that distribution's `status` to `pending` to request the URL check. The existing checker skips URLs already marked `active`.
- When correcting metadata, include a link to an authoritative source in your pull request description where possible.

The workflows reset publication flags to `false` after successful publication. **A `false` flag does not mean the KG is not published**; it normally means no new publication is currently requested.

## Contributing to development issues

We welcome contributions to the DBpedia KG Catalog and are happy to support and onboard new contributors. To keep feature discussions focused and help coordinate implementation, please use a **separate, linked issue** to propose work on an existing development issue.

### Proposing an implementation

1. Read the original issue and check whether an implementation proposal already exists.
2. [Open a regular GitHub issue](https://github.com/dbpedia/kg-catalog/issues/new/choose). Use a descriptive title such as `Contribution proposal: <feature> (#123)` and **reference the original issue** in the description (for example, `Proposed implementation for #123`).
3. Briefly explain your approach, intended code or documentation changes, expected outcome, and how you would test the contribution. A concise proposal is sufficient; you do not need a complete design in advance.
4. Discuss the proposal with maintainers in the **new issue**. We can help clarify the requirements, refine the approach, and agree on next steps before implementation begins.
5. Once the approach is agreed upon, submit a pull request referencing **both** the original development issue and the contribution proposal.

A contribution proposal is an **ordinary GitHub issue**.

### Commenting on development issues

Please keep comments on the original development issue focused on technical facts, questions, clarifications, and requirements relevant to the issue. Use the separate contribution proposal issue to discuss a particular implementation approach.

Avoid generic comments such as "Can I work on this?" or "Please assign this to me" without a concrete proposal. Maintainers may hide unrelated comments or close unsolicited pull requests that bypass this process.

### Exceptions

The separate proposal process is intended for **nontrivial development contributions**, such as new features, significant bug fixes, and architectural changes. **New KG registrations, KG metadata corrections, and small documentation fixes** can use the existing submission or pull-request process without opening an implementation proposal.

## What reviewers check

Reviewers should confirm that the KG ID is unique, the description and domain are appropriate, the license and download URLs are meaningful, the artifact/version structure is coherent, and no private credentials or irrelevant files are included. Publication should be authorized only for reviewed metadata.

For publication mechanics and troubleshooting, see [Automation](docs/automation.md) and [Operations](docs/operations.md).

## Reporting problems

- Metadata, submission, automation, and catalog processing: [kg-catalog issues](https://github.com/dbpedia/kg-catalog/issues)
- Website display, styling, and browser behavior: [kg-catalog-web issues](https://github.com/dbpedia/kg-catalog-web/issues)
