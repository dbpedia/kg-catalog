#!/usr/bin/env python3
"""Export KG-level metadata directly from live DBpedia MOSS (no Databus ZIP).

Python >=3.7. No mandatory third-party packages; pip install rdflib for RDF validation.
"""
import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://moss.dev.dbpedia.link'
GROUP_PREFIX = 'https://databus.dbpedia.org/knowledge-graph-catalog/'
QUERY = '''PREFIX databus: <https://dataid.dbpedia.org/databus#>
SELECT DISTINCT ?s WHERE {
  ?s a databus:Group .
  FILTER(STRSTARTS(STR(?s), "https://databus.dbpedia.org/knowledge-graph-catalog/"))
}
ORDER BY ?s'''
FIELDS = ['kg', 'group_uri', 'entry_url', 'content_url', 'file', 'content_type',
          'byte_size', 'sha256', 'triple_count', 'status', 'error']
LOG = logging.getLogger('moss-export')


def request(url, timeout, retries, data=None, accept='text/turtle'):
    headers = {'Accept': accept, 'User-Agent': 'kg-catalog-moss-export/1.1'}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib.request.Request(url, data=data, headers=headers)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(), response.headers.get('Content-Type', '')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, 'HTTP 404'
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError('Retries exhausted')


def validate_group(uri):
    if not uri.startswith(GROUP_PREFIX):
        raise ValueError('Outside KG Catalog account: ' + uri)
    kg = uri[len(GROUP_PREFIX):].rstrip('/')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', kg):
        raise ValueError('Invalid KG identifier: ' + uri)
    return kg


def discover(base, timeout, retries):
    body = urllib.parse.urlencode({'query': QUERY, 'format': 'application/sparql-results+json'}).encode('ascii')
    accept = 'application/sparql-results+json, application/json;q=0.9'
    # Some Virtuoso deployments reject anonymous SPARQL POST with HTTP 403,
    # while allowing read-only GET requests. Try GET first.
    query_url = base + '/sparql/?' + urllib.parse.urlencode({
        'query': QUERY, 'format': 'application/sparql-results+json'
    })
    try:
        raw, content_type = request(query_url, timeout, retries, accept=accept)
    except urllib.error.HTTPError as e:
        if e.code not in (403, 405, 414):
            raise
        LOG.warning('SPARQL GET returned HTTP %s; trying POST', e.code)
        raw, content_type = request(base + '/sparql/', timeout, retries, data=body, accept=accept)
    if not raw:
        raise RuntimeError('MOSS SPARQL discovery returned no data')
    try:
        parsed = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError('MOSS SPARQL returned non-JSON data (Content-Type: %s): %s' % (content_type, e))
    if 'results' not in parsed or 'bindings' not in parsed['results']:
        raise ValueError('Unexpected SPARQL JSON result: %s' % content_type)
    groups = {}
    for binding in parsed['results']['bindings']:
        val = binding['s']['value']
        groups[validate_group(val)] = GROUP_PREFIX + validate_group(val)
    if not groups:
        raise ValueError('MOSS discovery returned zero KG Catalog groups; refusing silent empty export')
    return groups, parsed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default=BASE, help='MOSS server (default: dev instance)')
    p.add_argument('--output', default='kg-level-metadata')
    p.add_argument('--kg', action='append', help='Fetch given KG directly, bypassing SPARQL (repeatable)')
    p.add_argument('--limit', type=int, default=0, help='First N discovered KGs; 0 means all')
    p.add_argument('--timeout', type=int, default=30)
    p.add_argument('--retries', type=int, default=2)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    base = args.base_url.rstrip('/')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    provenance = out / 'provenance'
    provenance.mkdir(parents=True, exist_ok=True)
    if args.kg:
        groups = {validate_group(GROUP_PREFIX + kg): GROUP_PREFIX + kg for kg in args.kg}
        LOG.info('Direct KG test mode: %d groups (no SPARQL discovery)', len(groups))
    else:
        groups, parsed = discover(base, args.timeout, args.retries)
        (provenance / 'discovery.sparql').write_text(QUERY + '\n', encoding='utf-8')
        (provenance / 'discovery.json').write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        LOG.info('Discovered %d KG Catalog groups in MOSS SPARQL', len(groups))
    items = sorted(groups.items())
    if args.limit > 0:
        items = items[:args.limit]
    manifest = []
    counts = {'ok': 0, 'missing': 0, 'failed': 0}
    for i, (kg, group_uri) in enumerate(items, 1):
        suffix = 'databus.dbpedia.org/knowledge-graph-catalog/%s/kg-metadata' % kg
        entry = base + '/entries/' + suffix
        url = base + '/g/content/' + suffix + '.ttl'
        dest = out / 'knowledge-graphs' / kg / 'kg-metadata.ttl'
        row = dict.fromkeys(FIELDS, '')
        row.update(kg=kg, group_uri=group_uri, entry_url=entry, content_url=url)
        try:
            raw, ctype = request(url, args.timeout, args.retries)
            if raw is None:
                row.update(status='missing', error='HTTP 404')
            elif not raw.strip() or raw.lstrip().lower().startswith((b'<html', b'<!doctype html')):
                raise ValueError('Empty or HTML response, not RDF Turtle')
            else:
                triples = ''
                try:
                    from rdflib import Graph, URIRef
                except ImportError:
                    LOG.warning('rdflib not installed: RDF syntax not checked for %s', kg)
                else:
                    g = Graph()
                    g.parse(data=raw, format='turtle', publicID=group_uri)
                    if not list(g.triples((URIRef(group_uri), None, None))):
                        raise ValueError('Turtle does not describe expected group: ' + group_uri)
                    triples = str(len(g))
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                row.update(file=str(dest.relative_to(out)), content_type=ctype,
                           byte_size=str(len(raw)), sha256=hashlib.sha256(raw).hexdigest(),
                           triple_count=triples, status='ok')
        except Exception as e:
            row.update(status='failed', error='%s: %s' % (type(e).__name__, e))
        counts[row['status']] += 1
        LOG.info('[%d/%d] %s %s %s', i, len(items), row['status'].upper(), kg, row['error'])
        manifest.append(row)
    with (provenance / 'manifest.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(manifest)
    LOG.info('Finished: %s; manifest: %s', counts, provenance / 'manifest.csv')
    return 1 if counts['failed'] else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        LOG.error('%s: %s', type(e).__name__, e)
        sys.exit(1)
