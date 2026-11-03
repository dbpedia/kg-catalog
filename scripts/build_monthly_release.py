#!/usr/bin/env python3
"""Validate and bundle the three KG Catalog exports into a monthly GitHub Release."""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import zipfile
from calendar import month_name
from datetime import datetime, timezone
from pathlib import Path

KINDS = ('kg-source-metadata', 'kg-release-metadata', 'kg-level-metadata')
LEGACY = {'kg-source-metadata': 'yaml_metadata',
          'kg-release-metadata': 'databus_metadata',
          'kg-level-metadata': 'moss_metadata'}
BASE_URL = 'https://github.com/dbpedia/kg-catalog'


def read_rows(path):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def previous_manifests(archive):
    result = {}
    if not archive:
        return result
    with zipfile.ZipFile(archive) as zf:
        for kind in KINDS:
            for candidate in (kind + '/provenance/manifest.csv', kind + '/manifest.csv',
                              LEGACY[kind] + '/provenance/manifest.csv',
                              LEGACY[kind] + '/manifest.csv'):
                try:
                    result[kind] = list(csv.DictReader(zf.read(candidate).decode('utf-8-sig').splitlines()))
                    break
                except KeyError:
                    pass
    return result


def keyset(rows, field):
    return {r[field] for r in rows if r.get('status') == 'ok' and r.get(field)}


def check_files(root, rows, relfield):
    for row in rows:
        if row.get('status') != 'ok':
            raise RuntimeError('%s: non-ok manifest entry: %s' % (root, row))
        relative = row.get(relfield, '')
        if not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise RuntimeError('Unsafe or missing file path in %s manifest: %s' % (root, relative))
        file = root / relative
        if not file.is_file():
            raise RuntimeError('Missing export file: %s' % file)
        if hashlib.sha256(file.read_bytes()).hexdigest() != row.get('sha256'):
            raise RuntimeError('Checksum mismatch: %s' % file)


def git_value(*args):
    try:
        return subprocess.check_output(['git'] + list(args), stderr=subprocess.DEVNULL,
                                       universal_newlines=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def resolve_software_version(commit):
    # The nearest reachable SemVer tag identifies the declared software baseline.
    # Metadata-only commits after that tag are allowed; the commit SHA stays authoritative.
    try:
        tags = subprocess.check_output(
            ['git', 'tag', '--merged', commit, '--list', 'v[0-9]*'],
            stderr=subprocess.DEVNULL, universal_newlines=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return ''
    tags = [t for t in tags if re.fullmatch(r'v\d+\.\d+\.\d+', t)]
    if not tags:
        return ''
    def dist(tag):
        try:
            return int(git_value('rev-list', '--count', '%s..%s' % (tag, commit)))
        except ValueError:
            return 2 ** 31
    return min(tags, key=lambda t: (dist(t), t))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release', required=True, help='kg-catalog-YYYY-MM')
    p.add_argument('--previous-archive', type=Path)
    p.add_argument('--previous-tag', default='')
    p.add_argument('--output', type=Path, default=Path('release-assets'))
    args = p.parse_args()
    match = re.fullmatch(r'kg-catalog-(\d{4})-(0[1-9]|1[0-2])', args.release)
    if not match:
        p.error('Release must be kg-catalog-YYYY-MM')
    title_month = '%s %s' % (month_name[int(match.group(2))], match.group(1))
    base = Path.cwd()
    manifests = {kind: read_rows(base / kind / 'provenance' / 'manifest.csv') for kind in KINDS}
    for kind, rows in manifests.items():
        if not rows:
            raise RuntimeError(kind + ': empty manifest')
    check_files(base / KINDS[0], manifests[KINDS[0]], 'path')
    check_files(base / KINDS[1], manifests[KINDS[1]], 'file')
    check_files(base / KINDS[2], manifests[KINDS[2]], 'file')
    hierarchy = read_rows(base / KINDS[1] / 'provenance' / 'hierarchy-manifest.csv')
    if not hierarchy:
        raise RuntimeError('Databus hierarchy manifest empty')
    check_files(base / KINDS[1], hierarchy, 'file')
    yaml_ids = keyset(manifests[KINDS[0]], 'kg_id')
    moss_ids = keyset(manifests[KINDS[2]], 'kg')
    version_uris = keyset(manifests[KINDS[1]], 'version_uri')
    databus_ids = {u.split('/')[4] for u in version_uris}
    group_ids = {r['resource_uri'].split('/')[4] for r in hierarchy if r.get('type') == 'group'}
    if not (yaml_ids == moss_ids == databus_ids == group_ids):
        raise RuntimeError('KG coverage mismatch: YAML=%s MOSS=%s Databus versions=%s Databus groups=%s' %
                           tuple(sorted(s) for s in (yaml_ids, moss_ids, databus_ids, group_ids)))
    if len({r['version_uri'] for r in manifests[KINDS[1]]}) != len(manifests[KINDS[1]]):
        raise RuntimeError('Duplicate Databus version URIs in manifest')
    if len({r['resource_uri'] for r in hierarchy}) != len(hierarchy):
        raise RuntimeError('Duplicate Databus hierarchy URIs in manifest')
    old = previous_manifests(args.previous_archive)
    commit = os.environ.get('GITHUB_SHA', '') or git_value('rev-parse', 'HEAD')
    version = os.environ.get('KG_CATALOG_SOFTWARE_VERSION', '') or (resolve_software_version(commit) if commit else '')
    run_url = os.environ.get('GITHUB_SERVER_URL', 'https://github.com') + '/' + os.environ.get('GITHUB_REPOSITORY', 'dbpedia/kg-catalog') + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', '') if os.environ.get('GITHUB_RUN_ID') else ''
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / (args.release + '.zip')
    info = {'catalog_release': args.release, 'snapshot_timestamp_utc': timestamp,
            'source_repository': BASE_URL, 'source_revision': commit or None,
            'kg_catalog_software_version': version or None,
            'software_version_tag_url': BASE_URL + '/tree/' + version if version else None,
            'release_workflow_execution_url': run_url or None,
            'metadata_sources': {'source': 'GitHub repository checkout',
                                 'release': 'https://databus.dbpedia.org',
                                 'level': 'https://moss.dev.dbpedia.link'},
            'counts': {'knowledge_graphs': len(yaml_ids), 'databus_versions': len(version_uris),
                       'databus_groups': len(group_ids),
                       'databus_artifacts': sum(r.get('type') == 'artifact' for r in hierarchy),
                       'moss_kg_entries': len(moss_ids)}}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for kind in KINDS:
            for file in sorted((base / kind).rglob('*')):
                if file.is_file():
                    zf.write(file, file.relative_to(base).as_posix())
        zf.writestr('release-info.json', json.dumps(info, indent=2) + '\n')
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (args.output / 'SHA256SUMS.txt').write_text('%s  %s\n' % (sha, archive.name), encoding='utf-8')
    lines = ['# DBpedia KG Catalog — ' + title_month, '']
    if len(old) == 3 and args.previous_tag:
        lines += ['This monthly release provides a snapshot of the DBpedia Knowledge Graph Catalog.','']
    else:
        lines += ['This is the first monthly release of the DBpedia Knowledge Graph Catalog. '
                  'It establishes the initial metadata snapshot, providing a baseline for tracking '
                  'the catalog\'s growth and evolution over time.', '']
    lines += ['## Catalog overview', '', '| Metadata collection | Description |', '|---|---|',
              '| **KG source metadata** | Original YAML descriptions of **%d knowledge graphs**, maintained on GitHub |' % len(yaml_ids),
              '| **KG release metadata** | RDF metadata describing **%d KG versions**, including their groups and artifacts, published on DBpedia Databus |' % len(version_uris),
              '| **KG-level metadata** | General RDF metadata for **%d knowledge graphs**, maintained in DBpedia MOSS |' % len(moss_ids), '']
    if len(old) == 3 and args.previous_tag:
        old_versions = keyset(old[KINDS[1]], 'version_uri')
        old_yaml = {r['kg_id']: r['sha256'] for r in old[KINDS[0]] if r.get('status') == 'ok'}
        new_yaml = {r['kg_id']: r['sha256'] for r in manifests[KINDS[0]] if r.get('status') == 'ok'}
        changed = sorted(k for k in old_yaml.keys() & new_yaml.keys() if old_yaml[k] != new_yaml[k])
        added = sorted(yaml_ids - set(old_yaml))
        removed = sorted(set(old_yaml) - yaml_ids)
        new_versions = version_uris - old_versions
        removed_versions = old_versions - version_uris
        lines += ['## Changes since ' + args.previous_tag, '',
                  '- **New knowledge graphs:** %d' % len(added),
                  '- **Removed knowledge graphs:** %d' % len(removed),
                  '- **Updated KG source metadata:** %d' % len(changed),
                  '- **Newly observed KG versions:** %d' % len(new_versions),
                  '- **Removed KG versions:** %d' % len(removed_versions), '']
        if added:
            lines += ['**New knowledge graphs:** ' + ', '.join('`%s`' % x for x in added), '']
        if changed:
            lines += ['**Updated KG source metadata:** ' + ', '.join('`%s`' % x for x in changed), '']
    lines += ['## Archive structure', '',
              'The release archive contains three metadata collections, each organized into two directories:', '',
              '- **`knowledge-graphs/`** — Exported metadata for individual knowledge graphs, organized by KG identifier. '
              'Depending on the collection, this includes YAML descriptions or RDF metadata describing KG groups, artifacts, versions, or KGs as a whole.',
              '- **`provenance/`** — Supporting export information, including metadata manifests, SHA-256 checksums, '
              'discovery queries (where applicable), and resources for tracing and verifying the snapshot.', '',
              'The complete metadata snapshot is available as a ZIP archive under the release assets. '
              'Use `SHA256SUMS.txt` to verify the archive.', '',
              '## Software and provenance', '',
              '- **Repository:** [dbpedia/kg-catalog](%s)' % BASE_URL]
    if version:
        lines.append('- **KG Catalog software:** [`%s`](%s/tree/%s)' % (version, BASE_URL, version))
    else:
        lines.append('- **KG Catalog software:** Not yet tagged (see source revision below)')
    if commit:
        lines.append('- **Source revision:** [`%s`](%s/commit/%s)' % (commit[:12], BASE_URL, commit))
    else:
        lines.append('- **Source revision:** Not available (local export)')
    lines.append('- **Snapshot timestamp:** `%s`' % timestamp)
    if run_url:
        lines.append('- **Release workflow execution:** [GitHub Actions run](%s)' % run_url)
    else:
        lines.append('- **Release workflow execution:** Local test run')
    lines += ['', '**Note:** The KG catalog releases contain metadata only, not the underlying knowledge graph datasets.', '']
    (args.output / 'release-notes.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Built %s and release-notes.md' % archive)
    print('KGs=%d, Databus versions=%d, Databus groups=%d, artifacts=%d, MOSS=%d' %
          (len(yaml_ids), len(version_uris), len(group_ids), info['counts']['databus_artifacts'], len(moss_ids)))


if __name__ == '__main__':
    main()
