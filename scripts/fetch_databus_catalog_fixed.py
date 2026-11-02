#!/usr/bin/env python3
"""Archive RDF metadata for every version in the DBpedia KG Catalog Databus account.

Requires: requests, rdflib. Supports Python 3.7+.
Usage: python fetch_databus_catalog_fixed.py --limit 3
"""
import argparse
import csv
import hashlib
import json
import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
from rdflib import Graph

BASE = 'https://databus.dbpedia.org'
ACCOUNT = BASE + '/knowledge-graph-catalog'
ENDPOINT = BASE + '/sparql'
CONTEXT = BASE + '/res/context.jsonld'
QUERY = '''PREFIX databus: <https://dataid.dbpedia.org/databus#>
SELECT DISTINCT ?version WHERE {
  ?version a databus:Version ;
           databus:account <https://databus.dbpedia.org/knowledge-graph-catalog> .
}
ORDER BY ?version
'''
NS = {'s': 'http://www.w3.org/2005/sparql-results#'}


def discover(session):
    response = session.get(ENDPOINT, params={'query': QUERY},
                           headers={'Accept': 'application/sparql-results+json, application/sparql-results+xml;q=0.9'},
                           timeout=90)
    response.raise_for_status()
    content_type = response.headers.get('Content-Type', '')
    logging.info('SPARQL response Content-Type: %s', content_type)
    if 'json' in content_type or response.text.lstrip().startswith('{'):
        data = response.json()
        result = [row['version']['value'] for row in data['results']['bindings']]
    else:
        root = ET.fromstring(response.content)
        result = [node.text for node in root.findall('.//s:result/s:binding[@name="version"]/s:uri', NS) if node.text]
    # Defensive URI validation; the query itself has no FILTER.
    result = sorted(set(uri for uri in result if uri.startswith(ACCOUNT + '/') and '#' not in uri))
    if not result:
        raise RuntimeError('SPARQL returned no catalog version URIs; check the account URI and endpoint response')
    return result


def save_context(session, output):
    response = session.get(CONTEXT, headers={'Accept': 'application/ld+json, application/json'}, timeout=60)
    response.raise_for_status()
    context = response.json()
    target = output / 'context.jsonld'
    target.write_text(json.dumps(context, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    logging.info('Saved JSON-LD context: %s (SHA-256 %s)', target, hashlib.sha256(target.read_bytes()).hexdigest())
    return context


def local_context_copy(document, context):
    """Replace the known remote context reference for offline RDF validation only."""
    if isinstance(document, list):
        return [local_context_copy(item, context) for item in document]
    if isinstance(document, dict):
        return {key: (context if key == '@context' and value == CONTEXT else local_context_copy(value, context))
                for key, value in document.items()}
    return document


def fetch_metadata(session, uri, context):
    failures = []
    for mime, extension, rdf_format in [('application/ld+json', 'jsonld', 'json-ld'),
                                        ('text/turtle', 'ttl', 'turtle')]:
        try:
            response = session.get(uri, headers={'Accept': mime}, timeout=90)
            response.raise_for_status()
            if extension == 'jsonld':
                document = response.json()
                # Validate using the stored copy of Databus's context rather than refetching it.
                graph = Graph()
                graph.parse(data=json.dumps(local_context_copy(document, context)), format='json-ld', publicID=uri)
                return response.content, extension, len(graph)
            graph = Graph()
            graph.parse(data=response.text, format=rdf_format, publicID=uri)
            return response.content, extension, len(graph)
        except Exception as exc:
            failures.append('{}: {}'.format(extension, exc))
    raise RuntimeError('; '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0, help='Download only the first N versions (0 = all)')
    parser.add_argument('--output', default='databus_metadata', help='Output directory')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'discovery.sparql').write_text(QUERY, encoding='utf-8')
    session = requests.Session()
    session.headers.update({'User-Agent': 'kg-catalog-metadata-export/1.0'})
    context = save_context(session, output)
    versions = discover(session)
    if args.limit > 0:
        versions = versions[:args.limit]
    logging.info('Discovered %d version URIs to fetch', len(versions))
    rows = []
    for i, uri in enumerate(versions, 1):
        parts = urlparse(uri).path.strip('/').split('/')
        # /knowledge-graph-catalog/<group>/<artifact>/<version>
        if len(parts) != 4 or parts[0] != 'knowledge-graph-catalog':
            logging.error('[%d/%d] INVALID VERSION URI %s', i, len(versions), uri)
            rows.append([uri, '', '', '', '', 'error', 'invalid version URI'])
            continue
        _, group, artifact, version = parts
        try:
            data, ext, count = fetch_metadata(session, uri, context)
            target_dir = output / group / artifact
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / (version + '.' + ext)
            target.write_bytes(data)
            sha256 = hashlib.sha256(data).hexdigest()
            rows.append([uri, str(target.relative_to(output)), ext, count, sha256, 'ok', ''])
            logging.info('[%d/%d] OK %s (%d triples, %s)', i, len(versions), uri, count, ext)
        except Exception as exc:
            rows.append([uri, '', '', '', '', 'error', str(exc)])
            logging.error('[%d/%d] FAILED %s: %s', i, len(versions), uri, exc)
    with (output / 'manifest.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['version_uri', 'file', 'format', 'triple_count', 'sha256', 'status', 'error'])
        writer.writerows(rows)
    ok = sum(row[5] == 'ok' for row in rows)
    logging.info('Finished: %d successful, %d failed. Manifest: %s', ok, len(rows) - ok, output / 'manifest.csv')
    if ok != len(rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
