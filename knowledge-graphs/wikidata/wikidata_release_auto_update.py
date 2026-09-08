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
REQUEST_HEADERS = {
    "User-Agent": (
        "kg-catalog-wikidata-release-updater/1.0 "
        "(https://www.dbpedia.org/)"
    ),
    "Accept-Encoding": "gzip",
}

FOLDER_PATTERN = re.compile(r'href="(\d{8})/"')
FILE_PATTERN = re.compile(r'href="([^"]+)"')

ARTIFACT_PATTERNS = {
    "truthy-beta": [
        ("nt", "bz2", "truthy", "nt.bz2"),
        ("nt", "gz", "truthy", "nt.gz"),
    ],
    "lexemes-beta": [
        ("nt", "bz2", "lexemes", "nt.bz2"),
        ("nt", "gz", "lexemes", "nt.gz"),
        ("ttl", "bz2", "lexemes", "ttl.bz2"),
        ("ttl", "gz", "lexemes", "ttl.gz"),
    ],
    "all-beta": [
        ("nt", "bz2", "all", "nt.bz2"),
        ("nt", "gz", "all", "nt.gz"),
        ("ttl", "bz2", "all", "ttl.bz2"),
        ("ttl", "gz", "all", "ttl.gz"),
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
    response = session.get(
        DUMPS_INDEX_URL, timeout=TIMEOUT, headers=REQUEST_HEADERS
    )
    response.raise_for_status()
    dates = {
        datetime.strptime(match, "%Y%m%d").date()
        for match in FOLDER_PATTERN.findall(response.text)
    }
    return sorted(dates)


def available_dump_files(version: date, session=requests) -> set[str]:
    url = f"{DUMPS_INDEX_URL}{version.strftime('%Y%m%d')}/"
    response = session.get(url, timeout=TIMEOUT, headers=REQUEST_HEADERS)
    response.raise_for_status()
    return {
        filename
        for filename in FILE_PATTERN.findall(response.text)
        if not filename.endswith("/")
    }


def expected_filenames(artifact_id: str, version: date) -> set[str]:
    version_string = version.strftime("%Y%m%d")
    return {
        f"wikidata-{version_string}-{dump_type}-BETA.{suffix}"
        for _, _, dump_type, suffix in ARTIFACT_PATTERNS[artifact_id]
    }


def latest_artifact_version(
    artifact_id: str, files_by_date: dict[date, set[str]]
) -> date | None:
    for version in sorted(files_by_date, reverse=True):
        if expected_filenames(artifact_id, version) <= files_by_date[version]:
            return version
    return None


def distribution_url(version: date, filename: str) -> str:
    return f"{DUMPS_INDEX_URL}{version.strftime('%Y%m%d')}/{filename}"


def fetch_file_size(url: str, session=requests) -> int:
    response = session.head(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
        headers=REQUEST_HEADERS,
    )
    response.raise_for_status()
    return int(response.headers.get("Content-Length", 0))


def build_version_entry(artifact: dict, version: date, license_url: str) -> dict:
    distributions = []
    version_string = version.strftime("%Y%m%d")
    for file_format, compression, dump_type, suffix in ARTIFACT_PATTERNS[artifact["artifact"]]:
        filename = f"wikidata-{version_string}-{dump_type}-BETA.{suffix}"
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


def update_artifact_if_needed(
    artifact: dict, newest_artifact_date: date | None, license_url: str
) -> bool:
    if newest_artifact_date is None:
        return False
    current_version = latest_catalogued_version(artifact)
    if newest_artifact_date <= current_version:
        return False
    artifact.setdefault("versions", []).append(
        build_version_entry(artifact, newest_artifact_date, license_url)
    )
    return True


def main() -> None:
    data = load_metadata()
    dump_dates = available_dump_dates()
    files_by_date = {
        version: available_dump_files(version) for version in dump_dates
    }
    license_url = str(data.get("license", ""))

    updated = False
    for artifact_id in ARTIFACT_PATTERNS:
        artifact = artifact_by_id(data, artifact_id)
        newest_artifact_date = latest_artifact_version(artifact_id, files_by_date)
        updated = update_artifact_if_needed(
            artifact, newest_artifact_date, license_url
        ) or updated

    if not updated:
        print("Wikidata metadata is already up to date.")
        return

    save_metadata(data)
    print("Added new Wikidata dump versions where needed.")


if __name__ == "__main__":
    main()
