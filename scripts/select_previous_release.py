#!/usr/bin/env python3
"""Choose the most recent *earlier* published KG Catalog monthly release.

Used by GitHub Actions after listing GitHub Releases and Git tags. Refuses a
misleading first-release baseline if older monthly tags exist without assets.
Writes mode=... and tag=... for $GITHUB_OUTPUT.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RELEASE_RE = re.compile(r'kg-catalog-\d{4}-(?:0[1-9]|1[0-2])\Z')


def select(current, releases_json, tags_text, limit=1000):
    if not RELEASE_RE.fullmatch(current):
        raise ValueError('Invalid current monthly release: ' + current)
    records = json.loads(releases_json)
    if not isinstance(records, list):
        raise ValueError('GitHub release response must be a JSON list')
    if len(records) >= limit:
        raise ValueError('Release listing might be truncated (%d results); '
                         'paginate instead of guessing the previous release' % limit)
    released = set()
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get('tagName'), str):
            raise ValueError('Unexpected GitHub release record: %r' % row)
        tag = row['tagName']
        if RELEASE_RE.fullmatch(tag):
            released.add(tag)
    git_tags = {t.strip() for t in tags_text.splitlines() if RELEASE_RE.fullmatch(t.strip())}
    if current in git_tags and current not in released:
        raise ValueError('Current monthly Git tag exists without a published GitHub Release: '
                         + current + '. Check for an incomplete previous publication.')
    missing_releases = sorted(t for t in git_tags - released if t < current)
    if missing_releases:
        raise ValueError('Earlier monthly Git tags without published GitHub Releases: %s. '
                         'Historical comparison would be incomplete.' % ', '.join(missing_releases))
    later = sorted(t for t in released if t > current)
    if later:
        raise ValueError('Cannot generate an older monthly snapshot after later releases exist: '
                         ', '.join(later))
    previous = sorted(t for t in released if t < current)
    if previous:
        return 'comparison', previous[-1]
    if released - {current} or any(t < current for t in git_tags):
        raise ValueError('No earlier published monthly release found, but monthly release '
                         'history exists; refusing to label this a first release')
    return 'baseline', ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', required=True)
    parser.add_argument('--releases-json', type=Path, required=True)
    parser.add_argument('--git-tags', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=1000)
    args = parser.parse_args()
    try:
        mode, previous = select(args.current, args.releases_json.read_text(encoding='utf-8'),
                                args.git_tags.read_text(encoding='utf-8'), args.limit)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print('ERROR: ' + str(e), file=sys.stderr)
        return 1
    print('mode=' + mode)
    print('tag=' + previous)
    print('Selected monthly release history: %s%s' %
          (mode, ' (' + previous + ')' if previous else ''), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
