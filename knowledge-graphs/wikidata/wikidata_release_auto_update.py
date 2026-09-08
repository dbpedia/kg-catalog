#!/usr/bin/env python3
"""Add new Wikidata dump versions to the KG Catalog metadata."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path

import requests
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
YAML_FILE = Path(os.environ.get("WIKIDATA_METADATA_FILE", SCRIPT_DIR / "metadata.yaml"))
DUMPS_INDEX_URL = "https://dumps.wikimedia.org/wikidatawiki/entities/"
TIMEOUT = 30
HARDCODED_SHA256 = "abcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcdabcd"

FOLDER_PATTERN = re.compile(r'href="(\d{8})/"')

ARTIFACT_PATTERNS = {
    "truthy-beta": [
        ("nt", "bz2", "latest-truthy.nt.bz2"),
        ("nt", "gz", "latest-truthy.nt.gz"),
    ],
    "lexemes-beta": [
        ("nt", "bz2", "latest-lexemes.nt.bz2"),
        ("nt", "gz", "latest-lexemes.nt.gz"),
        ("ttl", "bz2", "latest-lexemes.ttl.bz2"),
        ("ttl", "gz", "latest-lexemes.ttl.gz"),
    ],
    "all-beta": [
        ("nt", "bz2", "latest-all.nt.bz2"),
        ("nt", "gz", "latest-all.nt.gz"),
        ("ttl", "bz2", "latest-all.ttl.bz2"),
        ("ttl", "gz", "latest-all.ttl.gz"),
    ],
}


def load_metadata() -> dict:
    with YAML_FILE.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"{YAML_FILE} does not contain a metadata mapping")
    return data


def save_metadata(data: dict) -> None:
    with YAML_FILE.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)


def normalize_version(value) -> date:
    if hasattr(value, "year"):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def artifact_by_id(data: dict, artifact_id: str) -> dict:
    artifacts = [
        artifact for artifact in data.get("artifacts", [])
        if artifact.get("artifact") == artifact_id
    ]
    if len(artifacts) != 1:
        raise ValueError(f"expected exactly one {artifact_id} artifact, found {len(artifacts)}")
    return artifacts[0]


def latest_catalogued_version(artifact: dict) -> date:
    versions = artifact.get("versions", [])
    if not versions:
        raise ValueError(f"artifact {artifact.get('artifact')} has no versions")
    return max(normalize_version(entry["version"]) for entry in versions)


def available_dump_dates(session=requests) -> list[date]:
    response = session.get(DUMPS_INDEX_URL, timeout=TIMEOUT)
    response.raise_for_status()
    dates = {
        datetime.strptime(match, "%Y%m%d").date()
        for match in FOLDER_PATTERN.findall(response.text)
    }
    return sorted(dates)


def next_available_version(current_version: date, available_versions: list[date]) -> date | None:
    newer = [version for version in available_versions if version > current_version]
    return newer[-1] if newer else None


def distribution_url(version: date, filename: str) -> str:
    return f"{DUMPS_INDEX_URL}{version.strftime('%Y%m%d')}/{filename.replace('latest', version.strftime('%Y%m%d'))}"


def fetch_file_size(url: str, session=requests) -> int:
    response = session.head(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return int(response.headers.get("Content-Length", 0))


def build_version_entry(artifact: dict, version: date, license_url: str) -> dict:
    distributions = []
    for file_format, compression, filename in ARTIFACT_PATTERNS[artifact["artifact"]]:
        url = distribution_url(version, filename)
        distributions.append(
            {
                "file": url,
                "format": file_format,
                "compression": compression,
                "size": fetch_file_size(url),
                "sha256": HARDCODED_SHA256,
                "status": "pending",
            }
        )

    return {
        "version": version,
        "title": artifact["title"],
        "abstract": artifact.get("abstract"),
        "description": artifact.get("description"),
        "license": license_url,
        "distributions": distributions,
    }


def update_artifact_if_needed(artifact: dict, newest_dump_date: date, license_url: str) -> bool:
    current_version = latest_catalogued_version(artifact)
    next_version = next_available_version(current_version, [newest_dump_date])
    if next_version is None:
        return False
    artifact.setdefault("versions", []).append(build_version_entry(artifact, next_version, license_url))
    return True


def main() -> None:
    data = load_metadata()
    newest_dump_date = max(available_dump_dates())
    license_url = str(data.get("license", ""))

    updated = False
    for artifact_id in ARTIFACT_PATTERNS:
        artifact = artifact_by_id(data, artifact_id)
        updated = update_artifact_if_needed(artifact, newest_dump_date, license_url) or updated

    if not updated:
        print(f"Wikidata metadata is already up to date at {newest_dump_date}.")
        return

    save_metadata(data)
    print(f"Added Wikidata dump version {newest_dump_date} where needed.")


if __name__ == "__main__":
    main()
