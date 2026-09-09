#!/usr/bin/env python3

import argparse
import json
import sys
import requests


# =========================================================
# CONSTANTS
# =========================================================

SOURCE_BASE = "https://databus.dbpedia.org"
TARGET_BASE = "https://databus.dbpedia.org"

SOURCE_SPARQL = f"{SOURCE_BASE}/sparql"
PUBLISH_URL = f"{TARGET_BASE}/api/publish?fetch-file-properties=false"

CONTEXT = f"{TARGET_BASE}/res/context.jsonld"


# =========================================================
# DEBUG
# =========================================================

def debug(title, obj):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)

    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, indent=2, ensure_ascii=False))


def mask(headers):
    h = dict(headers)

    if "X-API-KEY" in h:
        h["X-API-KEY"] = "***REDACTED***"

    return h


# =========================================================
# JSON-LD HELPERS
# =========================================================

def all_nodes(data):
    if isinstance(data, dict):

        graph = data.get("@graph")

        if isinstance(graph, list):
            return graph

        if isinstance(graph, dict):
            return [graph]

        return [data]

    return []


def find_first(data, ttype):
    for node in all_nodes(data):

        t = node.get("@type")

        if t == ttype:
            return node

        if isinstance(t, list) and ttype in t:
            return node

    return None


def find_all(data, ttype):
    result = []

    for node in all_nodes(data):

        t = node.get("@type")

        if t == ttype:
            result.append(node)

        elif isinstance(t, list) and ttype in t:
            result.append(node)

    return result


# =========================================================
# HTTP
# =========================================================

session = requests.Session()


def fetch_jsonld(url):
    headers = {
        "accept": "application/ld+json"
    }

    debug("GET JSON-LD", {
        "url": url,
        "headers": headers
    })

    response = session.get(
        url,
        headers=headers,
        timeout=120
    )

    print("→ STATUS:", response.status_code)

    if response.status_code >= 400:
        print("❌ RESPONSE:")
        print(response.text)

    response.raise_for_status()

    return response.json()


def publish(payload, api_key):
    headers = {
        "accept": "application/json",
        "Content-Type": "application/ld+json",
        "X-API-KEY": api_key.strip()
    }

    debug("POST PUBLISH", {
        "url": PUBLISH_URL,
        "headers": mask(headers),
        "payload": payload
    })

    response = session.post(
        PUBLISH_URL,
        headers=headers,
        json=payload,
        timeout=120
    )

    print("→ STATUS:", response.status_code)

    if response.status_code >= 400:
        print("❌ RESPONSE:")
        print(response.text)

        response.raise_for_status()

    if response.text.strip():
        return response.json()

    return None


# =========================================================
# URI HELPERS
# =========================================================

def source_group_uri(
    source_account,
    source_group_id
):
    return (
        f"{SOURCE_BASE}/"
        f"{source_account.strip('/')}/"
        f"{source_group_id.strip('/')}"
    )


def target_group_uri(
    target_account,
    target_group_id
):
    return (
        f"{TARGET_BASE}/"
        f"{target_account.strip('/')}/"
        f"{target_group_id.strip('/')}"
    )


def target_artifact_uri(
    target_account,
    target_group_id,
    artifact_id
):
    group_uri = target_group_uri(
        target_account,
        target_group_id
    )

    return f"{group_uri}/{artifact_id}"


def target_version_uri(
    target_account,
    target_group_id,
    artifact_id,
    version_number
):
    artifact_uri = target_artifact_uri(
        target_account,
        target_group_id,
        artifact_id
    )

    return f"{artifact_uri}/{version_number}"


# =========================================================
# SPARQL
# =========================================================

def sparql(query):
    debug("SPARQL QUERY", query)

    response = session.post(
        SOURCE_SPARQL,
        data={
            "query": query
        },
        headers={
            "accept": "application/sparql-results+json"
        },
        timeout=120
    )

    print("→ STATUS:", response.status_code)

    if response.status_code >= 400:
        print("❌ RESPONSE:")
        print(response.text)

    response.raise_for_status()

    return response.json()


# =========================================================
# GROUP
# =========================================================

def fetch_group(source_group):

    data = fetch_jsonld(
        source_group
    )

    group = find_first(
        data,
        "Group"
    )

    if not group:
        raise Exception(
            f"Group node not found: {source_group}"
        )

    return group


def publish_group(
    target_group,
    target_group_name,
    source_group_data,
    api_key
):

    description = source_group_data.get(
        "description",
        ""
    )

    abstract = source_group_data.get(
        "abstract",
        ""
    )

    payload = {
        "@context": CONTEXT,
        "@graph": {
            "@type": "Group",
            "@id": target_group,
            "title": target_group_name,
            "description": description,
            "abstract": abstract
        }
    }

    print("\n################ GROUP ################")

    publish(
        payload,
        api_key
    )


# =========================================================
# ARTIFACTS
# =========================================================

def query_artifacts(source_group):

    query = f"""
PREFIX databus: <https://dataid.dbpedia.org/databus#>

SELECT DISTINCT ?artifact
WHERE {{
    ?version databus:group <{source_group}> .
    ?version databus:artifact ?artifact .
}}
ORDER BY ?artifact
"""

    data = sparql(query)

    return [
        binding["artifact"]["value"]
        for binding
        in data["results"]["bindings"]
    ]


def publish_artifact(
    target_account,
    target_group_id,
    artifact_id,
    source_artifact,
    api_key
):

    data = fetch_jsonld(
        source_artifact
    )

    artifact = find_first(
        data,
        "Artifact"
    )

    if not artifact:
        raise Exception(
            f"Artifact node missing: {source_artifact}"
        )

    target_id = target_artifact_uri(
        target_account,
        target_group_id,
        artifact_id
    )

    payload = {
        "@context": CONTEXT,
        "@graph": {
            "@type": "Artifact",
            "@id": target_id,
            "title": artifact.get(
                "title",
                artifact_id
            ),
            "description": artifact.get(
                "description",
                ""
            ),
            "abstract": artifact.get(
                "abstract",
                ""
            )
        }
    }

    print(
        "\n===== PUBLISH ARTIFACT =====",
        target_id
    )

    publish(
        payload,
        api_key
    )


# =========================================================
# VERSIONS
# =========================================================

def query_versions(
    source_group,
    source_artifact
):

    query = f"""
PREFIX databus: <https://dataid.dbpedia.org/databus#>

SELECT DISTINCT ?version
WHERE {{
    ?version databus:group <{source_group}> .
    ?version databus:artifact <{source_artifact}> .
}}
ORDER BY ?version
"""

    data = sparql(query)

    return [
        binding["version"]["value"]
        for binding
        in data["results"]["bindings"]
    ]


# =========================================================
# VERSION
# =========================================================

def extract_version_number(
    version_data,
    version_uri
):

    version = find_first(
        version_data,
        "Version"
    )

    if not version:
        raise Exception(
            f"Version node missing: {version_uri}"
        )

    return (
        version.get("hasVersion")
        or version_uri.rstrip("/").split("/")[-1]
    )


def copy_distribution(
    part,
    target_part_id
):

    distribution = {
        "@id": target_part_id,
        "@type": "Part"
    }

    # -----------------------------------------------------
    # Download URL
    # -----------------------------------------------------

    if part.get("downloadURL") is not None:
        distribution["downloadURL"] = (
            part["downloadURL"]
        )

    # -----------------------------------------------------
    # Checksum
    # -----------------------------------------------------

    if part.get("sha256sum") is not None:
        distribution["sha256sum"] = (
            part["sha256sum"]
        )

    # -----------------------------------------------------
    # File size
    # -----------------------------------------------------

    if part.get("dcat:byteSize") is not None:
        distribution["dcat:byteSize"] = (
            part["dcat:byteSize"]
        )

    # -----------------------------------------------------
    # Content variants
    # -----------------------------------------------------

    if part.get("dcv:graph") is not None:
        distribution["dcv:graph"] = (
            part["dcv:graph"]
        )

    if part.get("dcv:partition") is not None:
        distribution["dcv:partition"] = (
            part["dcv:partition"]
        )

    # -----------------------------------------------------
    # Compression
    # -----------------------------------------------------

    if part.get("compression") is not None:
        distribution["compression"] = (
            part["compression"]
        )

    # -----------------------------------------------------
    # Format extension
    # -----------------------------------------------------

    if part.get("formatExtension") is not None:
        distribution["formatExtension"] = (
            part["formatExtension"]
        )

    return distribution


def publish_version(
    target_account,
    target_group_id,
    artifact_id,
    source_version_uri,
    api_key
):

    data = fetch_jsonld(
        source_version_uri
    )

    version = find_first(
        data,
        "Version"
    )

    parts = find_all(
        data,
        "Part"
    )

    if not version:
        raise Exception(
            f"Version node missing: "
            f"{source_version_uri}"
        )

    version_number = extract_version_number(
        data,
        source_version_uri
    )

    target_version = target_version_uri(
        target_account,
        target_group_id,
        artifact_id,
        version_number
    )

    distributions = []

    for part in parts:

        part_id = part.get("@id")

        if not part_id:
            continue

        # -------------------------------------------------
        # Preserve fragment identifier
        # -------------------------------------------------

        if "#" in part_id:

            fragment = part_id.split(
                "#",
                1
            )[1]

            target_part_id = (
                f"{target_version}#{fragment}"
            )

        else:

            target_part_id = target_version

        distributions.append(
            copy_distribution(
                part,
                target_part_id
            )
        )

    payload = {
        "@context": CONTEXT,
        "@graph": {
            "@type": "Version",
            "@id": target_version,

            "title": version.get(
                "title",
                artifact_id
            ),

            "description": version.get(
                "description",
                ""
            ),

            "abstract": version.get(
                "abstract",
                ""
            ),

            "license": version.get(
                "license"
            ),

            "distribution": distributions
        }
    }

    print(
        "\n===== PUBLISH VERSION =====",
        target_version
    )

    print(
        f"    distributions: "
        f"{len(distributions)}"
    )

    publish(
        payload,
        api_key
    )


# =========================================================
# MAIN
# =========================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Copy a complete Databus group from "
            "one Databus account to another."
        )
    )

    # -----------------------------------------------------
    # SOURCE
    # -----------------------------------------------------

    parser.add_argument(
        "source_account",
        help="Source Databus account"
    )

    parser.add_argument(
        "source_group_id",
        help="Source group ID"
    )

    # -----------------------------------------------------
    # TARGET
    # -----------------------------------------------------

    parser.add_argument(
        "target_account",
        help="Target Databus account"
    )

    parser.add_argument(
        "target_group_id",
        help="Target group ID"
    )

    parser.add_argument(
        "target_group_name",
        help="Target group name/title"
    )

    parser.add_argument(
        "target_api_key",
        help="API key for the target Databus account"
    )

    args = parser.parse_args()

    # -----------------------------------------------------
    # API KEY
    # -----------------------------------------------------

    api_key = args.target_api_key.strip()

    if not api_key:
        print(
            "❌ Target Databus API key cannot be empty."
        )
        sys.exit(1)

    # -----------------------------------------------------
    # GROUP URIs
    # -----------------------------------------------------

    source_group = source_group_uri(
        args.source_account,
        args.source_group_id
    )

    target_group = target_group_uri(
        args.target_account,
        args.target_group_id
    )

    # -----------------------------------------------------
    # HEADER
    # -----------------------------------------------------

    print("\n")
    print("#" * 90)
    print("DATABUS GROUP COPY")
    print("#" * 90)

    print("\nSOURCE GROUP:")
    print(source_group)

    print("\nTARGET GROUP:")
    print(target_group)

    print("\nTARGET ACCOUNT:")
    print(args.target_account)

    print("\nTARGET GROUP ID:")
    print(args.target_group_id)

    # -----------------------------------------------------
    # GROUP
    # -----------------------------------------------------

    print("\n")
    print("#" * 90)
    print("COPYING GROUP")
    print("#" * 90)

    source_group_data = fetch_group(
        source_group
    )

    publish_group(
        target_group,
        args.target_group_name,
        source_group_data,
        api_key
    )

    # -----------------------------------------------------
    # ARTIFACTS
    # -----------------------------------------------------

    print("\n")
    print("#" * 90)
    print("COPYING ARTIFACTS")
    print("#" * 90)

    artifacts = query_artifacts(
        source_group
    )

    print(
        f"\nFOUND {len(artifacts)} ARTIFACTS"
    )

    failed_artifacts = []

    total_versions = 0
    failed_versions = []

    # -----------------------------------------------------
    # EACH ARTIFACT
    # -----------------------------------------------------

    for source_artifact in artifacts:

        artifact_id = (
            source_artifact
            .rstrip("/")
            .split("/")[-1]
        )

        print("\n")
        print("-" * 90)
        print(
            f"ARTIFACT: {artifact_id}"
        )
        print(
            f"SOURCE:   {source_artifact}"
        )

        try:

            # ---------------------------------------------
            # ARTIFACT
            # ---------------------------------------------

            publish_artifact(
                args.target_account,
                args.target_group_id,
                artifact_id,
                source_artifact,
                api_key
            )

            # ---------------------------------------------
            # VERSIONS
            # ---------------------------------------------

            versions = query_versions(
                source_group,
                source_artifact
            )

            print(
                f"\nFOUND {len(versions)} VERSIONS"
            )

            total_versions += len(versions)

            # ---------------------------------------------
            # EACH VERSION
            # ---------------------------------------------

            for source_version in versions:

                try:

                    publish_version(
                        args.target_account,
                        args.target_group_id,
                        artifact_id,
                        source_version,
                        api_key
                    )

                except Exception as e:

                    print(
                        "\n❌ FAILED VERSION:"
                    )

                    print(
                        source_version
                    )

                    print(e)

                    failed_versions.append(
                        source_version
                    )

        except Exception as e:

            print(
                "\n❌ FAILED ARTIFACT:"
            )

            print(
                source_artifact
            )

            print(e)

            failed_artifacts.append(
                source_artifact
            )

    # =====================================================
    # SUMMARY
    # =====================================================

    print("\n")
    print("#" * 90)
    print("COPY FINISHED")
    print("#" * 90)

    print(
        f"\nArtifacts found: {len(artifacts)}"
    )

    print(
        f"Versions found:  {total_versions}"
    )

    print(
        f"Failed artifacts: {len(failed_artifacts)}"
    )

    print(
        f"Failed versions:  {len(failed_versions)}"
    )

    if failed_artifacts:

        print("\nFAILED ARTIFACTS:")

        for artifact in failed_artifacts:
            print(
                f"  - {artifact}"
            )

    if failed_versions:

        print("\nFAILED VERSIONS:")

        for version in failed_versions:
            print(
                f"  - {version}"
            )

    if failed_artifacts or failed_versions:

        print(
            "\n⚠️ COPY COMPLETED WITH ERRORS."
        )

        sys.exit(1)

    print(
        "\n✅ GROUP COPIED SUCCESSFULLY."
    )


if __name__ == "__main__":
    main()