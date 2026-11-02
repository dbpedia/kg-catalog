#!/usr/bin/env python3
"""Bundle existing KG Catalog metadata exports and write reproducible release notes."""
import argparse
import csv
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def read_manifest(path):
    with path.open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def previous_manifests(archive):
    if not archive:
        return {}
    result = {}
    with zipfile.ZipFile(archive) as zf:
        for kind in ('yaml_metadata', 'moss_metadata', 'databus_metadata'):
            name = kind + '/manifest.csv'
            try:
                text = zf.read(name).decode('utf-8-sig').splitlines()
                result[kind] = list(csv.DictReader(text))
            except KeyError:
                pass
    return result


def keyset(rows, field):
    return {r[field] for r in rows if r.get('status') == 'ok' and r.get(field)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--release', required=True, help='Release tag e.g. kg-catalog-2026-11')
    p.add_argument('--previous-archive', type=Path)
    p.add_argument('--previous-tag', default='')
    p.add_argument('--output', type=Path, default=Path('release-assets'))
    args = p.parse_args()
    base = Path.cwd()
    kinds = ('yaml_metadata', 'databus_metadata', 'moss_metadata')
    manifests = {k: read_manifest(base / k / 'manifest.csv') for k in kinds}
    for kind, rows in manifests.items():
        if not rows or any(r.get('status') != 'ok' for r in rows):
            raise RuntimeError(kind + ': empty export or non-ok manifest records')
    yaml_ids = keyset(manifests['yaml_metadata'], 'kg_id')
    moss_ids = keyset(manifests['moss_metadata'], 'kg')
    databus_uris = keyset(manifests['databus_metadata'], 'version_uri')
    databus_ids = {u.split('/')[4] for u in databus_uris}
    if yaml_ids != moss_ids or yaml_ids != databus_ids:
        raise RuntimeError('KG coverage mismatch: YAML-only=%s MOSS-only=%s Databus-only=%s' %
                           (sorted(yaml_ids - moss_ids), sorted(moss_ids - yaml_ids), sorted(databus_ids - yaml_ids)))
    old = previous_manifests(args.previous_archive)
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / (args.release + '.zip')
    checksums = []
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for kind in kinds:
            for path in sorted((base / kind).rglob('*')):
                if path.is_file():
                    arcname = path.relative_to(base).as_posix()
                    zf.write(path, arcname)
                    checksums.append((arcname, hashlib.sha256(path.read_bytes()).hexdigest()))
        provenance = {
            'release_tag': args.release,
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'sources': {'yaml': 'GitHub repository checkout',
                        'databus': 'https://databus.dbpedia.org',
                        'moss': 'https://moss.dev.dbpedia.link'},
            'counts': {'kgs': len(yaml_ids), 'databus_versions': len(databus_uris), 'moss_kg_entries': len(moss_ids)}
        }
        zf.writestr('release-info.json', json.dumps(provenance, indent=2) + '\n')
    # Individual checksum file for the published release asset
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (args.output / 'SHA256SUMS.txt').write_text('%s  %s\n' % (digest, archive.name), encoding='utf-8')
    lines = [
        '# KG Catalog metadata snapshot — ' + args.release,
        '',
        'Monthly snapshot of **catalog metadata** (not the KG datasets themselves).',
        '',
        '## Contents',
        '',
        '- **GitHub YAML:** %d knowledge graph descriptions, preserved byte-for-byte.' % len(yaml_ids),
        '- **DBpedia Databus:** %d artifact-version metadata documents.' % len(databus_uris),
        '- **DBpedia MOSS (development endpoint):** %d KG-level RDF metadata documents.' % len(moss_ids),
        '',
    ]
    if len(old) == 3 and args.previous_tag:
        old_versions = keyset(old['databus_metadata'], 'version_uri')
        old_yaml = {r['kg_id']: r['sha256'] for r in old['yaml_metadata'] if r.get('status') == 'ok'}
        new_yaml = {r['kg_id']: r['sha256'] for r in manifests['yaml_metadata'] if r.get('status') == 'ok'}
        changed = sorted(k for k in old_yaml.keys() & new_yaml.keys() if old_yaml[k] != new_yaml[k])
        added = sorted(yaml_ids - set(old_yaml))
        removed = sorted(set(old_yaml) - yaml_ids)
        new_versions = sorted(databus_uris - old_versions)
        removed_versions = sorted(old_versions - databus_uris)
        lines += ['## Changes since ' + args.previous_tag, '',
                  '- Newly cataloged KGs: **%d**' % len(added),
                  '- Removed KGs: **%d**' % len(removed),
                  '- Changed YAML descriptions: **%d**' % len(changed),
                  '- Newly observed Databus versions: **%d**' % len(new_versions),
                  '- Databus versions no longer present: **%d**' % len(removed_versions), '']
        if added:
            lines += ['**Added KGs:** ' + ', '.join('`'+x+'`' for x in added), '']
        if changed:
            lines += ['**Updated YAML:** ' + ', '.join('`'+x+'`' for x in changed), '']
        if new_versions:
            lines += ['**New Databus versions** (first 30 shown):', '']
            lines += ['- ' + u for u in new_versions[:30]]
            if len(new_versions) > 30:
                lines += ['- ...and %d more (see metadata manifests).' % (len(new_versions)-30)]
            lines += ['']
    else:
        lines += ['## Baseline', '',
                  'This is the initial snapshot or no previous comparable snapshot was available. '
                  'A month-over-month difference is not reported.', '']
    lines += ['## Provenance and integrity', '',
              'The ZIP includes original metadata documents, per-source `manifest.csv` files, '
              'discovery metadata where available, and `release-info.json`. '
              'Use `SHA256SUMS.txt` to verify the downloaded ZIP.', '',
              '**Note:** MOSS metadata is currently sourced from a development service and may differ from production.', '']
    (args.output / 'release-notes.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Built', archive, 'and release-notes.md')

if __name__ == '__main__':
    main()
