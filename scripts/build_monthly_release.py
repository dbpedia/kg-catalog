#!/usr/bin/env python3
"""Validate exports; build an analysis-ready monthly KG Catalog metadata snapshot.

The first release must explicitly use --first-release. Every later release must
supply --previous-tag and --previous-archive; missing history is a fatal error.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from calendar import month_name
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml
from rdflib import Graph, URIRef
from rdflib.compare import to_isomorphic

KINDS = ('kg-source-metadata', 'kg-release-metadata', 'kg-level-metadata')
LEGACY = {
    'kg-source-metadata': 'yaml_metadata',
    'kg-release-metadata': 'databus_metadata',
    'kg-level-metadata': 'moss_metadata',
}
BASE_URL = 'https://github.com/dbpedia/kg-catalog'
DATABUS_ACCOUNT = 'https://databus.dbpedia.org/knowledge-graph-catalog/'
CONTEXT_URL = 'https://databus.dbpedia.org/res/context.jsonld'
ISSUED = URIRef('http://purl.org/dc/terms/issued')
FORMAT = URIRef('https://dataid.dbpedia.org/databus#formatExtension')
RELEASE_RE = re.compile(r'kg-catalog-(\d{4})-(0[1-9]|1[0-2])\Z')

ANALYSIS_GUIDE = """# Analyzing KG Catalog monthly snapshots

This archive preserves full source YAML, Databus RDF, and MOSS RDF metadata,
plus two machine-readable files for longitudinal analysis.

## catalog-summary.csv

One row per KG per monthly snapshot; concatenate files across months using
`snapshot_id` and `kg_id` as a composite key.

- `databus_artifact_count` / `databus_version_count`: number of published
  Databus artifact and version metadata records in this snapshot.
- `databus_formats`: semicolon-separated values of `databus:formatExtension`
  declared in version RDF files. These are reported metadata, not verified files.
- `latest_databus_version_issued_at_utc`: latest `dcterms:issued` date from
  Databus *version descriptions*. This is a Databus publication timestamp, not
  necessarily when a KG's underlying data changed or when the version first
  appeared in the catalog. The matching URI is in `latest_databus_version_uri`.
- `source_license` and `title` are taken from the source YAML, not inferred
  from the Databus or MOSS descriptions.
- `*_present` flags indicate metadata successfully exported at the snapshot.
  The release validation requires complete matching KG sets across sources.

## changes.json

`comparison_status: baseline` and `collections: null` indicate the first
snapshot: there is no prior release to compare, **not zero historical changes**.

For a comparison snapshot, five categories report `added`, `removed`, and
`modified` resource identifiers: YAML KG descriptions; Databus groups,
artifacts and versions; and MOSS KG-level descriptions. Each record has the
old/new serialized SHA-256 as applicable, allowing exact file retrieval via
its respective manifest.

YAML is classified as modified when its original bytes change (even comments).
RDF is classified as modified only when the **parsed RDF graphs differ**. If
serialized RDF bytes change but the graphs are equivalent, the record instead
appears under `serialization_only_changes` and counts as semantically unchanged.
RDF comparisons include the entire exported description, which may contain
triples about linked entities; a change is not necessarily confined to one
property of the named resource.

## Interpretation

Snapshots are collected sequentially from GitHub, Databus, and MOSS, not as a
single atomic transaction. Compare the full snapshots or the machine-readable
change report; do not interpret newly observed version URIs as necessarily
created or released within the reporting month. SHA-256 integrity checksums
are recorded in per-source manifests, and the archive's own checksum is in the
separate GitHub Release asset `SHA256SUMS.txt`.
"""


def read_csv_bytes(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))


def read_csv_file(path):
    return read_csv_bytes(path.read_bytes())


def valid_relative(value):
    p = PurePosixPath(value)
    return bool(value) and not p.is_absolute() and '..' not in p.parts and '\\' not in value


def validate_rows(rows, kind, collection, get_bytes, field):
    if not rows:
        raise RuntimeError('%s %s: empty or missing manifest' % (kind, collection))
    for row in rows:
        if row.get('status') != 'ok':
            raise RuntimeError('%s %s: non-OK manifest entry: %s' % (kind, collection, row))
        rel = row.get(field, '')
        if not valid_relative(rel):
            raise RuntimeError('%s %s: unsafe/missing path: %r' % (kind, collection, rel))
        try:
            raw = get_bytes(kind, rel)
        except (KeyError, FileNotFoundError) as e:
            raise RuntimeError('%s %s: missing file %s' % (kind, collection, rel)) from e
        if hashlib.sha256(raw).hexdigest() != row.get('sha256'):
            raise RuntimeError('%s %s: checksum mismatch for %s' % (kind, collection, rel))


def tracked_files(manifests, hierarchy, kind):
    field = 'path' if kind == KINDS[0] else 'file'
    result = {r[field] for r in manifests[kind]}
    if kind == KINDS[1]:
        result.update(r['file'] for r in hierarchy)
    return result


def validate_no_unmanifested_files(manifests, hierarchy, present_files):
    for kind in KINDS:
        recorded = tracked_files(manifests, hierarchy, kind)
        untracked = sorted(present_files(kind) - recorded)
        if untracked:
            raise RuntimeError('%s: %d unmanifested metadata files, e.g. %s. '
                               'Use clean export directories before packaging.' %
                               (kind, len(untracked), untracked[:5]))


def inventory(rows, key, label):
    out = {}
    for row in rows:
        ident = row.get(key, '')
        if not ident or ident in out:
            raise RuntimeError('%s: missing/duplicate identifier %r' % (label, ident))
        out[ident] = row
    return out


def kg_from_uri(uri, depth):
    if not uri.startswith(DATABUS_ACCOUNT):
        raise RuntimeError('Unexpected Databus account URI: ' + uri)
    parts = uri[len(DATABUS_ACCOUNT):].split('/')
    if len(parts) != depth or not all(parts):
        raise RuntimeError('Unexpected Databus URI structure: ' + uri)
    return parts[0]


def git_value(*args):
    try:
        return subprocess.check_output(['git'] + list(args), stderr=subprocess.DEVNULL,
                                       universal_newlines=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def resolve_software_version(commit):
    if not commit:
        return ''
    try:
        tags = subprocess.check_output(
            ['git', 'tag', '--merged', commit, '--list', 'v[0-9]*'],
            stderr=subprocess.DEVNULL, universal_newlines=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return ''
    tags = [t for t in tags if re.fullmatch(r'v\d+\.\d+\.\d+', t)]
    if not tags:
        return ''

    def distance(tag):
        try:
            return int(git_value('rev-list', '--count', '%s..%s' % (tag, commit)))
        except ValueError:
            return 2 ** 31
    return min(tags, key=lambda t: (distance(t), t))


class CurrentSnapshot:
    def __init__(self, base):
        self.base = base
        self.manifests = {
            k: read_csv_file(base / k / 'provenance' / 'manifest.csv') for k in KINDS
        }
        self.hierarchy = read_csv_file(
            base / 'kg-release-metadata' / 'provenance' / 'hierarchy-manifest.csv')
        self.context = json.loads((base / 'kg-release-metadata' / 'provenance' /
                                   'context.jsonld').read_text(encoding='utf-8'))
        for kind in KINDS:
            field = 'path' if kind == KINDS[0] else 'file'
            validate_rows(self.manifests[kind], kind, 'manifest', self.read, field)
        validate_rows(self.hierarchy, KINDS[1], 'hierarchy-manifest', self.read, 'file')
        validate_coverage(self.manifests, self.hierarchy)
        validate_no_unmanifested_files(self.manifests, self.hierarchy, self.metadata_files)

    def metadata_files(self, kind):
        root = self.base / kind
        return {p.relative_to(root).as_posix() for p in
                (root / 'knowledge-graphs').rglob('*') if p.is_file()}

    def read(self, kind, rel):
        return (self.base / kind / rel).read_bytes()

    def close(self):
        pass


class ArchivedSnapshot:
    def __init__(self, archive, previous_tag):
        if not archive.is_file():
            raise RuntimeError('Previous archive not found: %s' % archive)
        self.zf = zipfile.ZipFile(archive)
        self.prefix = {}
        names = set(self.zf.namelist())
        self.manifests = {}
        try:
            metadata = json.loads(self.zf.read('release-info.json'))
        except (KeyError, json.JSONDecodeError) as e:
            raise RuntimeError('Previous archive lacks valid release-info.json') from e
        if metadata.get('catalog_release') != previous_tag:
            raise RuntimeError('Previous archive tag mismatch: expected %s, got %s' %
                               (previous_tag, metadata.get('catalog_release')))
        for kind in KINDS:
            candidates = [
                (kind, kind + '/provenance/manifest.csv'),
                (kind, kind + '/manifest.csv'),
                (LEGACY[kind], LEGACY[kind] + '/provenance/manifest.csv'),
                (LEGACY[kind], LEGACY[kind] + '/manifest.csv'),
            ]
            found = next(((prefix, name) for prefix, name in candidates if name in names), None)
            if found is None:
                raise RuntimeError('Previous archive missing %s manifest' % kind)
            self.prefix[kind] = found[0]
            self.manifests[kind] = read_csv_bytes(self.zf.read(found[1]))

        candidates = [self.prefix[KINDS[1]] + '/provenance/hierarchy-manifest.csv',
                      self.prefix[KINDS[1]] + '/hierarchy-manifest.csv']
        hierarchy_name = next((n for n in candidates if n in names), None)
        if hierarchy_name is None:
            raise RuntimeError('Previous archive lacks Databus hierarchy-manifest.csv; '
                               'cannot compare groups and artifacts reliably')
        self.hierarchy = read_csv_bytes(self.zf.read(hierarchy_name))
        contexts = [self.prefix[KINDS[1]] + '/provenance/context.jsonld',
                    self.prefix[KINDS[1]] + '/context.jsonld']
        ctx_name = next((n for n in contexts if n in names), None)
        if ctx_name is None:
            raise RuntimeError('Previous archive missing Databus JSON-LD context')
        self.context = json.loads(self.zf.read(ctx_name))
        for kind in KINDS:
            field = 'path' if kind == KINDS[0] else 'file'
            validate_rows(self.manifests[kind], kind, 'previous manifest', self.read, field)
        validate_rows(self.hierarchy, KINDS[1], 'previous hierarchy', self.read, 'file')
        validate_coverage(self.manifests, self.hierarchy)
        validate_no_unmanifested_files(self.manifests, self.hierarchy, self.metadata_files)

    def metadata_files(self, kind):
        prefix = self.prefix[kind] + '/'
        return {n[len(prefix):] for n in self.zf.namelist()
                if n.startswith(prefix + 'knowledge-graphs/') and not n.endswith('/')}

    def read(self, kind, rel):
        return self.zf.read(self.prefix[kind] + '/' + rel)

    def close(self):
        self.zf.close()


def validate_coverage(manifests, hierarchy):
    yaml_ids = set(inventory(manifests[KINDS[0]], 'kg_id', 'YAML').keys())
    moss_ids = set(inventory(manifests[KINDS[2]], 'kg', 'MOSS').keys())
    version_ids = inventory(manifests[KINDS[1]], 'version_uri', 'Databus versions')
    hierarchy_ids = inventory(hierarchy, 'resource_uri', 'Databus hierarchy')
    if any(r.get('type') not in ('group', 'artifact') for r in hierarchy):
        raise RuntimeError('Unknown Databus hierarchy record type')
    group_ids = {kg_from_uri(u, 1) for u, r in hierarchy_ids.items() if r['type'] == 'group'}
    artifact_ids = {kg_from_uri(u, 2) for u, r in hierarchy_ids.items() if r['type'] == 'artifact'}
    version_kg_ids = {kg_from_uri(u, 3) for u in version_ids}
    if not (yaml_ids == moss_ids == group_ids == artifact_ids == version_kg_ids):
        raise RuntimeError('KG coverage mismatch: YAML=%s MOSS=%s Databus groups=%s '
                           'artifacts=%s versions=%s' %
                           tuple(sorted(x) for x in (yaml_ids, moss_ids, group_ids,
                                                     artifact_ids, version_kg_ids)))
    # Ensure every version belongs to an exported artifact, not just an exported group.
    artifact_uris = {u for u, r in hierarchy_ids.items() if r['type'] == 'artifact'}
    for version_uri in version_ids:
        if version_uri.rsplit('/', 1)[0] not in artifact_uris:
            raise RuntimeError('Version has no exported artifact: %s' % version_uri)
    return yaml_ids


def replace_context(obj, context):
    if isinstance(obj, list):
        return [replace_context(x, context) for x in obj]
    if isinstance(obj, dict):
        return {k: (context if k == '@context' and v == CONTEXT_URL
                    else replace_context(v, context)) for k, v in obj.items()}
    return obj


def parse_rdf(snapshot, kind, row, uri):
    raw = snapshot.read(kind, row['file'])
    rdf_format = row.get('format') or Path(row['file']).suffix.lstrip('.')
    graph = Graph()
    if rdf_format in ('jsonld', 'json-ld'):
        parsed = json.loads(raw.decode('utf-8'))
        graph.parse(data=json.dumps(replace_context(parsed, snapshot.context)),
                    format='json-ld', publicID=uri)
    elif rdf_format in ('ttl', 'turtle'):
        graph.parse(data=raw.decode('utf-8'), format='turtle', publicID=uri)
    else:
        raise RuntimeError('Unsupported RDF format %r in %s' % (rdf_format, row['file']))
    return graph


def canonical_utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return ''
        return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except ValueError:
        return ''


def write_summary(snapshot, kg_ids, release, timestamp, outpath):
    yaml_rows = inventory(snapshot.manifests[KINDS[0]], 'kg_id', 'YAML')
    moss_rows = inventory(snapshot.manifests[KINDS[2]], 'kg', 'MOSS')
    groups = {}
    artifacts_by_kg = Counter()
    for r in snapshot.hierarchy:
        uri = r['resource_uri']
        if r['type'] == 'group':
            groups[kg_from_uri(uri, 1)] = r
        else:
            artifacts_by_kg[kg_from_uri(uri, 2)] += 1
    versions_by_kg = Counter()
    formats_by_kg = defaultdict(set)
    latest_by_kg = {}  # kg_id -> (ISO date, version_uri)
    for row in snapshot.manifests[KINDS[1]]:
        uri = row['version_uri']
        kg = kg_from_uri(uri, 3)
        versions_by_kg[kg] += 1
        graph = parse_rdf(snapshot, KINDS[1], row, uri)
        formats_by_kg[kg].update(str(o) for o in graph.objects(None, FORMAT))
        for issued in graph.objects(URIRef(uri), ISSUED):
            date = canonical_utc(str(issued))
            if date:
                current = (date, uri)
                if current > latest_by_kg.get(kg, ('', '')):
                    latest_by_kg[kg] = current
    fieldnames = [
        'snapshot_id', 'snapshot_timestamp_utc', 'kg_id', 'title', 'source_license',
        'source_metadata_present', 'databus_group_metadata_present',
        'databus_artifact_count', 'databus_version_count',
        'databus_formats', 'latest_databus_version_issued_at_utc',
        'latest_databus_version_uri', 'kg_level_metadata_present',
    ]
    with outpath.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for kg in sorted(kg_ids):
            record = yaml.safe_load(snapshot.read(KINDS[0], yaml_rows[kg]['path']))
            if not isinstance(record, dict):
                raise RuntimeError('Invalid YAML description for %s' % kg)
            last_date, last_uri = latest_by_kg.get(kg, ('', ''))
            writer.writerow({
                'snapshot_id': release,
                'snapshot_timestamp_utc': timestamp,
                'kg_id': kg,
                'title': str(record.get('title') or ''),
                'source_license': str(record.get('license') or ''),
                'source_metadata_present': 'true',
                'databus_group_metadata_present': str(kg in groups).lower(),
                'databus_artifact_count': artifacts_by_kg[kg],
                'databus_version_count': versions_by_kg[kg],
                'databus_formats': ';'.join(sorted(formats_by_kg[kg])),
                'latest_databus_version_issued_at_utc': last_date,
                'latest_databus_version_uri': last_uri,
                'kg_level_metadata_present': str(kg in moss_rows).lower(),
            })


def build_delta(before, after, before_snapshot, after_snapshot, kind, rdf):
    previous = set(before)
    current = set(after)
    added = [{'id': k, 'sha256': after[k]['sha256']} for k in sorted(current - previous)]
    removed = [{'id': k, 'sha256': before[k]['sha256']} for k in sorted(previous - current)]
    modified, reserialized = [], []
    unchanged = 0
    for ident in sorted(previous & current):
        left, right = before[ident], after[ident]
        if left['sha256'] == right['sha256']:
            unchanged += 1
            continue
        entry = {'id': ident, 'previous_sha256': left['sha256'],
                 'current_sha256': right['sha256']}
        if rdf:
            try:
                old_graph = parse_rdf(before_snapshot, kind, left, ident)
                new_graph = parse_rdf(after_snapshot, kind, right, ident)
                same = to_isomorphic(old_graph) == to_isomorphic(new_graph)
            except Exception as exc:
                raise RuntimeError('Cannot compare RDF metadata for %s: %s' %
                                   (ident, exc)) from exc
            if same:
                reserialized.append(entry)
                unchanged += 1
                continue
        modified.append(entry)
    return {
        'added': added,
        'removed': removed,
        'modified': modified,
        'serialization_only_changes': reserialized if rdf else [],
        'unchanged_count': unchanged,
        'counts': {
            'added': len(added), 'removed': len(removed), 'modified': len(modified),
            'serialization_only_changes': len(reserialized), 'unchanged': unchanged,
        },
    }


def make_changes(previous, current, release, previous_tag, timestamp):
    result = {
        'schema_version': '1.0',
        'release': release,
        'previous_release': previous_tag or None,
        'snapshot_timestamp_utc': timestamp,
        'comparison_status': 'compared' if previous else 'baseline',
        'comparison_method': {
            'resource_identity': 'KG ID or RDF resource URI',
            'yaml_modification': 'SHA-256 of original YAML bytes',
            'rdf_modification': 'RDF graph isomorphism when SHA-256 differs',
            'serialization_only_changes': 'RDF bytes changed but RDF graph is unchanged',
        },
        'collections': None,
    }
    if not previous:
        result['explanation'] = 'First snapshot: no previous monthly release to compare.'
        return result

    curr_yaml = inventory(current.manifests[KINDS[0]], 'kg_id', 'current YAML')
    prev_yaml = inventory(previous.manifests[KINDS[0]], 'kg_id', 'previous YAML')
    curr_ver = inventory(current.manifests[KINDS[1]], 'version_uri', 'current versions')
    prev_ver = inventory(previous.manifests[KINDS[1]], 'version_uri', 'previous versions')
    curr_moss = inventory(current.manifests[KINDS[2]], 'group_uri', 'current MOSS')
    prev_moss = inventory(previous.manifests[KINDS[2]], 'group_uri', 'previous MOSS')

    def hierarchy_map(snapshot, typ):
        return inventory([row for row in snapshot.hierarchy if row['type'] == typ],
                         'resource_uri', 'Databus %s' % typ)

    result['collections'] = {
        'kg_source_metadata': build_delta(prev_yaml, curr_yaml, previous, current,
                                          KINDS[0], rdf=False),
        'kg_release_metadata': {
            'groups': build_delta(hierarchy_map(previous, 'group'), hierarchy_map(current, 'group'),
                                  previous, current, KINDS[1], rdf=True),
            'artifacts': build_delta(hierarchy_map(previous, 'artifact'), hierarchy_map(current, 'artifact'),
                                     previous, current, KINDS[1], rdf=True),
            'versions': build_delta(prev_ver, curr_ver, previous, current,
                                    KINDS[1], rdf=True),
        },
        'kg_level_metadata': build_delta(prev_moss, curr_moss, previous, current,
                                         KINDS[2], rdf=True),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True, help='kg-catalog-YYYY-MM')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--first-release', action='store_true', help='Explicitly establish initial baseline')
    group.add_argument('--previous-archive', type=Path, help='Previous published snapshot ZIP')
    parser.add_argument('--previous-tag', default='', help='Tag matching --previous-archive')
    parser.add_argument('--output', type=Path, default=Path('release-assets'))
    args = parser.parse_args()
    match = RELEASE_RE.fullmatch(args.release)
    if not match:
        parser.error('Release must be kg-catalog-YYYY-MM')
    if args.first_release and args.previous_tag:
        parser.error('--first-release must not be used with --previous-tag')
    if args.previous_archive and (not RELEASE_RE.fullmatch(args.previous_tag)
                                  or args.previous_tag >= args.release):
        parser.error('A valid older --previous-tag is required with --previous-archive')
    title_month = '%s %s' % (month_name[int(match.group(2))], match.group(1))
    current = CurrentSnapshot(Path.cwd())
    previous = None
    try:
        if args.previous_archive:
            previous = ArchivedSnapshot(args.previous_archive, args.previous_tag)
        commit = os.environ.get('GITHUB_SHA', '') or git_value('rev-parse', 'HEAD')
        version = os.environ.get('KG_CATALOG_SOFTWARE_VERSION', '') or (
            resolve_software_version(commit) if commit else '')
        run_url = (os.environ.get('GITHUB_SERVER_URL', 'https://github.com') + '/' +
                   os.environ.get('GITHUB_REPOSITORY', 'dbpedia/kg-catalog') + '/actions/runs/' +
                   os.environ['GITHUB_RUN_ID']) if os.environ.get('GITHUB_RUN_ID') else ''
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        ids = validate_coverage(current.manifests, current.hierarchy)
        args.output.mkdir(parents=True, exist_ok=True)
        summary_file = args.output / 'catalog-summary.csv'
        # Write data files into the release root, not merely beside the ZIP.
        write_summary(current, ids, args.release, timestamp, summary_file)
        changes = make_changes(previous, current, args.release, args.previous_tag, timestamp)
        changes_file = args.output / 'changes.json'
        changes_file.write_text(json.dumps(changes, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

        info = {
            'catalog_release': args.release,
            'snapshot_timestamp_utc': timestamp,
            'source_repository': BASE_URL,
            'source_revision': commit or None,
            'kg_catalog_software_version': version or None,
            'software_version_tag_url': BASE_URL + '/tree/' + version if version else None,
            'release_workflow_execution_url': run_url or None,
            'previous_release': args.previous_tag or None,
            'comparison_status': changes['comparison_status'],
            'analysis_schema_version': changes['schema_version'],
            'metadata_sources': {
                'source': 'GitHub repository checkout',
                'release': 'https://databus.dbpedia.org',
                'level': 'https://moss.dev.dbpedia.link',
            },
            'counts': {
                'knowledge_graphs': len(ids),
                'databus_versions': len(current.manifests[KINDS[1]]),
                'databus_groups': sum(r['type'] == 'group' for r in current.hierarchy),
                'databus_artifacts': sum(r['type'] == 'artifact' for r in current.hierarchy),
                'moss_kg_entries': len(current.manifests[KINDS[2]]),
            },
        }
        archive = args.output / (args.release + '.zip')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for kind in KINDS:
                for file in sorted((current.base / kind).rglob('*')):
                    if file.is_file():
                        zf.write(file, file.relative_to(current.base).as_posix())
            for analysis in (summary_file, changes_file):
                zf.write(analysis, analysis.name)
            zf.writestr('ANALYSIS.md', ANALYSIS_GUIDE)
            zf.writestr('release-info.json', json.dumps(info, indent=2) + '\n')
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        (args.output / 'SHA256SUMS.txt').write_text(
            '%s  %s\n' % (sha, archive.name), encoding='utf-8')

        lines = ['# DBpedia KG Catalog — ' + title_month, '']
        if previous:
            lines += ['This monthly release provides a snapshot of the DBpedia Knowledge Graph Catalog.', '']
        else:
            lines += ['This is the first monthly release of the DBpedia Knowledge Graph Catalog. '
                      'It establishes the initial metadata snapshot, providing a baseline for tracking '
                      'the catalog\'s growth and evolution over time.', '']
        lines += [
            '## Catalog overview', '',
            '| Metadata collection | Description |', '|---|---|',
            '| **KG source metadata** | Original YAML descriptions of **%d knowledge graphs**, maintained on GitHub |' % len(ids),
            '| **KG release metadata** | RDF metadata describing **%d KG versions**, including their groups and artifacts, published on DBpedia Databus |' % len(current.manifests[KINDS[1]]),
            '| **KG-level metadata** | General RDF metadata for **%d knowledge graphs**, maintained in DBpedia MOSS |' % len(current.manifests[KINDS[2]]),
            '',
        ]
        if previous:
            cs = changes['collections']
            changes_table = [
                ('Knowledge graphs (YAML)', cs['kg_source_metadata']),
                ('Databus groups', cs['kg_release_metadata']['groups']),
                ('Databus artifacts', cs['kg_release_metadata']['artifacts']),
                ('Databus versions', cs['kg_release_metadata']['versions']),
                ('MOSS KG metadata', cs['kg_level_metadata']),
            ]
            lines += [
                '## Changes since ' + args.previous_tag, '',
                '| Metadata | Added | Removed | Modified |',
                '|---|---:|---:|---:|',
            ]
            lines += [
                '| %s | %d | %d | %d |' % (name, block['counts']['added'],
                                          block['counts']['removed'], block['counts']['modified'])
                for name, block in changes_table
            ]
            lines.append('')
            added_kgs = [a['id'] for a in cs['kg_source_metadata']['added']]
            changed_kgs = [a['id'] for a in cs['kg_source_metadata']['modified']]
            if added_kgs:
                lines += ['**New knowledge graphs:** ' + ', '.join('`%s`' % x for x in added_kgs), '']
            if changed_kgs:
                lines += ['**Updated KG source metadata:** ' + ', '.join('`%s`' % x for x in changed_kgs), '']
            lines += ['For the complete machine-readable change report, see `changes.json` in the archive.', '']
        lines += [
            '## Archive structure', '',
            'The release archive contains three metadata collections, each organized into two directories:', '',
            '- **`knowledge-graphs/`** — Exported metadata for individual knowledge graphs, organized by KG identifier. '
            'Depending on the collection, this includes YAML descriptions or RDF metadata describing KG groups, artifacts, versions, or KGs as a whole.',
            '- **`provenance/`** — Supporting export information, including metadata manifests, SHA-256 checksums, '
            'discovery queries (where applicable), and resources for tracing and verifying the snapshot.', '',
            'For historical analysis, `catalog-summary.csv` provides one row per KG and `changes.json` '
            'records changes against the previous release (or identifies this first release as a baseline). '
            'Field definitions and comparison semantics are documented in `ANALYSIS.md`.', '',
            'The complete metadata snapshot is available as a ZIP archive under the release assets. '
            'Use `SHA256SUMS.txt` to verify the archive.', '',
            '## Software and provenance', '',
            '- **Repository:** [dbpedia/kg-catalog](%s)' % BASE_URL,
        ]
        if version:
            lines.append('- **KG Catalog software:** [`%s`](%s/tree/%s)' % (version, BASE_URL, version))
        else:
            lines.append('- **KG Catalog software:** Not yet tagged (see source revision below)')
        if commit:
            lines.append('- **Source revision:** [`%s`](%s/commit/%s)' % (commit[:12], BASE_URL, commit))
        else:
            lines.append('- **Source revision:** Not available (local export)')
        lines.append('- **Snapshot timestamp:** `%s`' % timestamp)
        lines.append('- **Release workflow execution:** [GitHub Actions run](%s)' % run_url
                     if run_url else '- **Release workflow execution:** Local test run')
        lines += ['', '**Note:** The KG catalog releases contain metadata only, '
                  'not the underlying knowledge graph datasets.', '']
        (args.output / 'release-notes.md').write_text('\n'.join(lines), encoding='utf-8')
        print('Built %s and release-notes.md' % archive)
        print('KGs=%d, Databus groups=%d, artifacts=%d, versions=%d, MOSS=%d' % (
            len(ids), info['counts']['databus_groups'], info['counts']['databus_artifacts'],
            info['counts']['databus_versions'], info['counts']['moss_kg_entries']))
        print('Comparison: %s; analysis: catalog-summary.csv, changes.json' %
              changes['comparison_status'])
    finally:
        if previous:
            previous.close()
        current.close()


if __name__ == '__main__':
    main()
