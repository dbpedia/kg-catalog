#!/usr/bin/env python3
"""Snapshot the KG Catalog's authoritative YAML metadata without altering content.

Run from the repository root: python scripts/export_yaml_catalog.py
Or point to the clone: python export_yaml_catalog.py --repo /path/to/kg-catalog
"""
import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

LOG = logging.getLogger('yaml-export')

def git_revision(repo):
    try:
        return subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None

def export(repo, output, make_zip=True, validate=True):
    source = repo / 'knowledge-graphs'
    if not source.is_dir():
        raise ValueError(f'No knowledge-graphs directory at {source}')
    files = sorted(source.glob('*/metadata.yaml'))
    if not files:
        raise ValueError(f'No metadata.yaml files found beneath {source}')
    if output.resolve() == repo.resolve() or output.resolve() == source.resolve():
        raise ValueError('Output must not overwrite repository or knowledge-graphs directory')
    yaml_lib = None
    if validate:
        try:
            import yaml as yaml_lib
        except ImportError:
            raise RuntimeError('PyYAML needed for validation. Install: python -m pip install pyyaml')
    if output.exists():
        shutil.rmtree(output)
    out_kg = output / 'knowledge-graphs'
    out_kg.mkdir(parents=True)
    revision = git_revision(repo)
    ref = revision or 'main'
    base = 'https://github.com/dbpedia/kg-catalog'
    raw_base = 'https://raw.githubusercontent.com/dbpedia/kg-catalog'
    if not revision:
        LOG.warning('No Git commit detected; GitHub links will use the mutable main branch')
    rows = []
    for path in files:
        kg_id = path.parent.name
        raw = path.read_bytes()
        if validate:
            obj = yaml_lib.safe_load(raw)
            if not isinstance(obj, dict):
                raise ValueError(f'Not a YAML mapping: {path}')
            if obj.get('id') != kg_id:
                raise ValueError(f'KG ID mismatch in {path}: {obj.get("id")!r} != {kg_id!r}')
        relative = Path('knowledge-graphs') / kg_id / 'metadata.yaml'
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        rel = relative.as_posix()
        rows.append({'kg_id': kg_id, 'path': rel,
                     'github_url': f'{base}/blob/{ref}/{rel}',
                     'raw_url': f'{raw_base}/{ref}/{rel}',
                     'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'ok'})
        LOG.info('[%d/%d] OK %s', len(rows), len(files), kg_id)
    provenance = output / 'provenance'
    provenance.mkdir(parents=True, exist_ok=True)
    with (provenance / 'manifest.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['kg_id', 'path', 'github_url', 'raw_url', 'bytes', 'sha256', 'status'])
        writer.writeheader()
        writer.writerows(rows)
    info = {'source': 'GitHub repository YAML source of truth', 'repository': 'https://github.com/dbpedia/kg-catalog', 'revision': revision, 'github_link_ref': ref, 'exported_at_utc': datetime.now(timezone.utc).isoformat(), 'knowledge_graph_count': len(rows), 'yaml_files': len(rows), 'validation': 'PyYAML parse and id-match' if validate else 'not requested'}
    (provenance / 'export-info.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    if make_zip:
        archive = output.with_suffix('.zip')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for file in sorted(output.rglob('*')):
                if file.is_file():
                    zf.write(file, file.relative_to(output.parent))
        LOG.info('ZIP: %s', archive)
    LOG.info('Finished: %d YAML files; manifest: %s', len(rows), provenance / 'manifest.csv')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'), help='Local KG catalog repository root (default: current directory)')
    parser.add_argument('--output', type=Path, default=Path('yaml_metadata'), help='Output directory (default: yaml_metadata)')
    parser.add_argument('--no-zip', action='store_true', help='Do not create a ZIP archive')
    parser.add_argument('--no-validate', action='store_true', help='Skip PyYAML schema-independent parse and KG ID checks')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        export(args.repo.resolve(), args.output.resolve(), not args.no_zip, not args.no_validate)
    except Exception as e:
        LOG.error('%s: %s', type(e).__name__, e)
        sys.exit(1)
