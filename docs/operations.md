# Operations and maintainer runbook

This guide is for maintainers operating the GitHub-based KG Catalog automation. It is not a guide for deploying the Databus or MOSS servers themselves; refer to their own repositories for that infrastructure.

## Operating model

The catalog's metadata and automation live in [dbpedia/kg-catalog](https://github.com/dbpedia/kg-catalog). The website lives in [dbpedia/kg-catalog-web](https://github.com/dbpedia/kg-catalog-web), a separate static frontend. The processing workflows depend on GitHub Actions, Databus, MOSS, and external dataset download URLs.

Primary maintenance activities are validating contributions, reviewing PRs, checking scheduled workflows, responding to publication failures, and verifying monthly metadata releases.

## Required access

- **Repository:** Permission to review/merge pull requests and read GitHub Actions logs.
- **Actions:** Permission to run workflows manually; appropriate GitHub Actions permissions enabled for commits/PRs/workflow dispatch and releases.
- **Databus:** `KNOWLEDGE_GRAPH_CATALOG` secret, holding the API key for the `knowledge-graph-catalog` Databus account.
- **MOSS:** `MOSS_KG_CATALOG` secret, holding a MOSS API key used by publishing and enrichment scripts.
- **Additional integration:** Some workflows expose `DEUTSCHE_NATBIB`, although current KG YAML records use the Databus `knowledge-graph-catalog` account.

**Never** put tokens in source-controlled files, tickets, screenshots, or logs. Rotate keys according to service procedures if a secret is exposed.

## Where to inspect status

| What | Where |
| --- | --- |
| Submission processing | [Validate New KG Submission workflow](https://github.com/dbpedia/kg-catalog/actions/workflows/validate-new-kg.yml) and Issue comments |
| Publication | [Check URLs & Publish Knowledge Graphs workflow](https://github.com/dbpedia/kg-catalog/actions/workflows/check_and_publish.yml) |
| New-release detection | [Daily KG Release Check workflow](https://github.com/dbpedia/kg-catalog/actions/workflows/daily_check.yml) |
| MOSS enrichment | [Update KG catalog sizes workflow](https://github.com/dbpedia/kg-catalog/actions/workflows/update_kg_sizes.yml) |
| Monthly snapshots | [Monthly metadata release workflow](https://github.com/dbpedia/kg-catalog/actions/workflows/monthly-metadata-release.yml) |
| Public catalog | https://kg-catalog.dbpedia.org/ |
| Published Databus entries | https://databus.dbpedia.org/knowledge-graph-catalog |
| GitHub Releases | https://github.com/dbpedia/kg-catalog/releases |

A green GitHub Action does not guarantee that all external KGs are downloadable. Particularly, the daily update driver catches and logs individual KG script failures without necessarily failing the job.

## Routine checks

**After a merged metadata change:**

1. Verify that the change appears on `main` under the expected KG directory.
2. Inspect the publication workflow outcome; look for requested Databus/MOSS publication and any updated YAML statuses/flags.
3. Verify the Databus group URI and relevant published version metadata.
4. Verify relevant MOSS values and the website entry.
5. If metadata differs across systems, investigate before triggering a rerun; external publication and YAML commits are not atomic.

**Weekly:** Review failed or suspicious daily-release checks, distribution URL errors, and any direct pull requests that may not have received automated checks. Review the hourly MOSS-enrichment workflow for repeated service errors.

**Monthly:** Inspect the candidate/published metadata snapshot, verify source coverage and checksum, and review release-notes accuracy. Check that GitHub release archive contents agree with the expected source revision.

## Safe local metadata checks

Use an isolated Python environment if preferred. For checks that do **not** publish to external services:

```bash
python3 -m pip install 'PyYAML>=6,<7'
python3 scripts/export_yaml_catalog.py --repo . --output /tmp/kg-catalog-source-check --no-zip
```

This confirms YAML parsing and directory/ID matching, but not all required metadata fields, URLs, or external service behavior. For scripts involving SPARQL/RDF, `requests` and `rdflib` are commonly required; check the specific script and workflow before running.

Avoid calling publisher or removal scripts directly during routine verification: they may mutate external systems.

## Troubleshooting guide

| Symptom | Check | Recovery principle |
| --- | --- | --- |
| New KG Issue does not generate PR | `new-kg` label, validation comment, workflow run, bot PR permissions | Correct the issue; rerun or investigate permissions; do not bypass review |
| Duplicate KG ID accepted | `validate_new_kg.py` currently checks `kgs/` rather than `knowledge-graphs/` | Fix validator; inspect for collisions before merging |
| Direct PR lacks validation result | No dedicated `pull_request` validation workflow currently configured | Manually validate YAML and structure; add PR CI as a future improvement |
| Dataset remains `pending`/`error` | URL HEAD status, redirects, publisher restrictions, network, `status` field | Correct or verify the URL; do not mark `active` without evidence |
| Databus publish fails | API key, account, Databus response, distribution checksum/size, endpoint availability | Restore access and fix metadata; rerun only after identifying partial publications |
| MOSS publish fails | `MOSS_KG_CATALOG`, endpoint, Turtle payload, service availability | Verify whether `moss.dev.dbpedia.link` is intended; reconcile state before rerun |
| Daily workflow is green but a KG did not update | Individual updater logs in `daily_check.py` output | Repair the KG-specific script; check source URLs; rerun with review |
| Monthly snapshot fails | Databus/MOSS availability, source coverage, export manifests, prior Release asset | Resolve source mismatch; start with manual dry run, do not fake a baseline |
| Website shows stale/missing entry | Databus and MOSS published metadata; frontend browser/API errors | Identify whether issue belongs to metadata pipeline or `kg-catalog-web` |

## Manual workflow dispatch

Use the **Actions** tab and select the existing workflow. Start with non-destructive checks. `monthly-metadata-release.yml` supports a dry-run option; publication or maintenance scripts generally do **not** provide a universal dry-run mode.

Never enable broad automated publication solely to test credentials. Use an isolated endpoint/test account where possible, or review the intended API calls before a manual run.

## Download testing

For maintainers testing dataset availability, `scripts/download-all-kgs.sh` discovers KGs from Databus, invokes `databusclient`, and writes per-KG logs and a CSV report. It may download **very large** files and can require authentication for some distributions.

Example of a deliberately limited test:

```bash
MAX_KGS=2 PARALLEL_DOWNLOADS=2 \
  OUTPUT_DIR=/tmp/kg-catalog-download-test \
  bash scripts/download-all-kgs.sh
```

`MAX_KGS` limits the first KGs returned by the discovery order, not a named test selection. Additional controls include `GROUPS_FILE`, `MAX_SECONDS`, `DISCOVERY_TIMEOUT`, `PARALLEL_DOWNLOADS`, and `OUTPUT_DIR`. Consult the script before running against large sources. A local file named `scripts/vault-token.dat` is read automatically if present: keep it out of Git and secure its permissions. The repository does not currently include a `.gitignore`; adding exclusions for credentials and generated files is a high-priority maintenance improvement.

For ordinary catalog users, point to the [public download guide](https://kg-catalog.dbpedia.org/download.html).

## Recovery principles

- **GitHub metadata:** Restore an erroneous YAML change through a reviewed revert/fix PR, then republish affected records intentionally.
- **Databus/MOSS divergence:** Compare source YAML, Databus, and MOSS; determine which publication step failed. Do not assume a GitHub rerun automatically rolls back already published external metadata.
- **Monthly release failure:** Use the manual dry run to diagnose. Avoid publishing incomplete metadata or overwriting an earlier historical snapshot.
- **External dataset outage:** Contact the KG publisher or correct the distribution metadata; GitHub Actions cannot repair an external data server.

## Development issue notice

When creating a development issue, maintainers can include the following notice at the end of the issue description to guide potential contributors:

---

**Interested in contributing?**

We welcome new contributors and are happy to help you get started! Before commenting, please read our [Development Contribution Guidelines](https://github.com/dbpedia/kg-catalog/blob/main/CONTRIBUTING.md#contributing-to-development-issues). If you would like to work on this issue, please open a separate issue referencing this one and briefly describe your proposed approach.

## Known improvements to prioritize

1. Add a schema-backed **pull-request validation** workflow for every `knowledge-graphs/**/*.yaml` change.
2. Correct the duplicate-KG lookup path in `scripts/validate_new_kg.py`.
3. Decide and document the intended **production MOSS endpoint** (currently development URL is hardcoded in several scripts).
4. Add an appropriate `.gitignore` and clarify repository code/data licensing (the repository does not currently include a LICENSE file).
5. Add lightweight script tests/fixtures and documented expectations for checksum handling and external publication errors.
6. Define and test a rollback/reconciliation procedure for partial Databus/MOSS publication.

Track these as GitHub Issues rather than describing them as already implemented.
