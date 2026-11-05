# GitHub Actions and automated workflows

This page documents the automation present in the repository. The descriptions below refer to implemented triggers and steps, not intended future behavior.

## Workflow inventory

| Workflow | Trigger | Main purpose |
| --- | --- | --- |
| [`validate-new-kg.yml`](../.github/workflows/validate-new-kg.yml) | Issue opened or edited, with label `new-kg` | Validate Issue-form submission, generate YAML, open a PR |
| [`check_and_publish.yml`](../.github/workflows/check_and_publish.yml) | Push to `main` changing KG YAML; manual dispatch | Check non-active URLs, publish selected records to Databus and MOSS, commit YAML updates |
| [`daily_check.yml`](../.github/workflows/daily_check.yml) | Daily at **01:00 UTC**; manual dispatch | Run KG-specific new-release checkers, commit updates, dispatch publication |
| [`update_kg_sizes.yml`](../.github/workflows/update_kg_sizes.yml) | Hourly at **:26 UTC**; manual; successful publication workflow completion | Refresh KG size and 180-day update-frequency data in MOSS |
| [`monthly-metadata-release.yml`](../.github/workflows/monthly-metadata-release.yml) | First of month at **06:17 UTC**; manual dispatch | Create metadata-only snapshots with changes, provenance, and GitHub Release assets |
| [`test-wikimedia-access.yml`](../.github/workflows/test-wikimedia-access.yml) | Manual dispatch | Diagnostic check of Wikimedia dump access through curl and Python requests |

GitHub scheduling is best effort: actual execution can be delayed.

## 1. Submission and pull-request creation

**Entry:** GitHub Issue form at `.github/ISSUE_TEMPLATE/new-kg-submission.yml`.

**Automation:** `validate-new-kg.yml` invokes `scripts/validate_new_kg.py`, posts a validation comment, and on success calls `scripts/generate_metadata.py` followed by `peter-evans/create-pull-request`.

**Review:** A maintainer reviews the generated PR. The workflow does **not** automatically merge it.

**Important:** `validate-new-kg.yml` only reacts to matching **Issue events**, not arbitrary `pull_request` events. Direct YAML pull requests are not currently validated by a dedicated CI workflow. Also, `validate_new_kg.py` checks ID collisions under `kgs/<id>/metadata.yaml`, while catalog files actually live under `knowledge-graphs/<id>/metadata.yaml`; this should be corrected before relying on duplicate detection.

## 2. URL checks and external publication

`check_and_publish.yml` runs after a push to `main` touching KG YAML, or manually. It performs these steps in order:

1. Install Python 3.11, `pyyaml`, and `requests`.
2. Run `scripts/check_url_update_yaml.py` for **all** KG YAML files. Distributions already marked `active` are skipped. Pending/non-active distribution URLs are checked with HTTP HEAD; status updates may set `databus-publish: true` when a URL becomes active.
3. Run `scripts/publish_to_databus_http.py` for each YAML. The script publishes only if `databus-publish: true`; the account API key is supplied through an environment variable derived from `databus-account`.
4. Run `scripts/publish_to_moss_http.py` for each YAML. The script publishes only if `moss-publish: true` and currently targets the configured MOSS development endpoint.
5. Commit any modified YAML (publication flags and status fields) back to `main`.

**Limits and risks:** This pipeline publishes to external services before the final YAML commit. A failure can leave external services ahead of GitHub metadata or can prevent a later step from running. The publication scripts also make external requests (including potential full-file checksum downloads). These actions should be tested without live publication when making changes.

## 3. Daily discovery of new KG releases

`daily_check.yml` runs `scripts/daily_check.py`. The script iterates over KG folders, reads `check-new-release`, and invokes the named Python script beside that KG's YAML. Examples include the DBLP, DBnary, SSTIM, and Wikidata update scripts.

The workflow then commits changed YAML and dispatches `check_and_publish.yml`. Individual KG-check subprocess failures are logged, but `daily_check.py` catches them and continues, rather than necessarily failing the whole job. **Review the logs**, not just the workflow's green status.

## 4. MOSS enrichment

`update_kg_sizes.yml` runs `scripts/update_kg_sizes.py` and `scripts/update_kg_update_frequency.py` using Databus SPARQL and MOSS APIs. The workflow is triggered hourly, on demand, and after successful completion of the publication workflow.

These scripts update **derived MOSS values**, not necessarily the GitHub source YAML. The `MOSS_KG_CATALOG` secret must be available.

## 5. Monthly metadata snapshot

`monthly-metadata-release.yml` collects GitHub source YAML, Databus RDF metadata, and MOSS RDF metadata, validates coverage, compares against the previous monthly snapshot, and creates a ZIP plus a checksum and release notes.

- Scheduled runs publish a GitHub Release automatically (if the pipeline succeeds).
- Manual runs default to **dry run** (`publish: false`), uploading a short-lived Actions artifact without creating a GitHub Release.
- Manual runs with `publish: true` publish the GitHub Release.
- Existing published monthly releases are not silently overwritten.
- A missing or incomplete previous release is treated as an error rather than silently creating a misleading baseline.

See [Releases](releases.md) for archive layout and interpretation.

## Permissions and secrets

The workflows request specific `GITHUB_TOKEN` write permissions where they need to commit files, create PRs, dispatch another workflow, or publish Releases. GitHub repository settings must allow these operations.

| Variable/secret | Purpose |
| --- | --- |
| `KNOWLEDGE_GRAPH_CATALOG` | Databus API key for `knowledge-graph-catalog` publication |
| `MOSS_KG_CATALOG` | MOSS API key for KG metadata publication and enrichment |
| `DEUTSCHE_NATBIB` | Made available to some workflows for Databus publication under that account, although current source records use `knowledge-graph-catalog` |
| `GITHUB_TOKEN` | GitHub Actions authentication for PR creation, workflow dispatch, and releases |

Never put secret values in documentation, Issue templates, YAML, or workflow logs.

## Responsibility matrix

| Event | Source YAML | Databus | MOSS | GitHub Release |
| --- | --- | --- | --- | --- |
| Approved KG metadata merged | New/updated, then flags/status may change | Republish if requested | Republish if requested | No immediate snapshot |
| Daily new-release detection | May add new versions | Triggered separately if requested | Can be updated afterward | No immediate snapshot |
| Hourly enrichment | Usually unchanged | Read source | Update derived metrics | No |
| Monthly snapshot | Read | Read/export | Read/export | Publish metadata archive if successful |

For response to failures and manual procedures, see [Operations](operations.md).
