#!/usr/bin/env python3

import argparse
import json
import os
import sys
import requests


# =========================================================
# CONSTANTS
# =========================================================

SOURCE_GROUP = (
    "https://databus.dbpedia.org/knowledge-graph-catalog/"
    "dbpedia-wikipedia-kg-all-languages"
)

SPARQL_ENDPOINT = "https://databus.dbpedia.org/sparql"

PUBLISH_URL = (
    "https://databus.dbpedia.org/api/publish"
    "?fetch-file-properties=false"
)

TARGET_BASE = (
    "https://databus.dbpedia.org/knowledge-graph-catalog"
)


# =========================================================
# DEBUG
# =========================================================

def debug(title, obj):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)
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
    """
    Normalize JSON-LD into a list of nodes.
    """

    if isinstance(data, dict):

        graph = data.get("@graph")

        if isinstance(graph, list):
            return graph

        if isinstance(graph, dict):
            return [graph]

        return [data]

    return []


def find_first(data, ttype):
    """
    Find the first JSON-LD node of the requested @type.
    """

    for node in all_nodes(data):

        node_type = node.get("@type")

        if node_type == ttype:
            return node

        if isinstance(node_type, list) and ttype in node_type:
            return node

    return None


def find_all(data, ttype):
    """
    Find all JSON-LD nodes of the requested @type.
    """

    result = []

    for node in all_nodes(data):

        node_type = node.get("@type")

        if node_type == ttype:
            result.append(node)

        elif isinstance(node_type, list) and ttype in node_type:
            result.append(node)

    return result


# =========================================================
# HTTP
# =========================================================

def fetch_jsonld(url):

    headers = {
        "accept": "application/ld+json"
    }

    debug(
        "GET",
        {
            "url": url,
            "headers": headers
        }
    )

    r = requests.get(url, headers=headers)

    print("→ STATUS:", r.status_code)

    if r.status_code >= 400:

        print("❌ RESPONSE:", r.text)

    r.raise_for_status()

    return r.json()


def publish(payload, api_key):

    headers = {
        "accept": "application/json",
        "Content-Type": "application/ld+json",
        "X-API-KEY": api_key.strip()
    }

    debug(
        "POST PUBLISH",
        {
            "url": PUBLISH_URL,
            "headers": mask(headers),
            "payload": payload
        }
    )

    r = requests.post(
        PUBLISH_URL,
        headers=headers,
        json=payload
    )

    print("→ STATUS:", r.status_code)

    if r.status_code >= 400:

        print("❌ RESPONSE:", r.text)
        sys.exit(1)

    return r.json()


# =========================================================
# GROUP
# =========================================================

def fetch_group():

    data = fetch_jsonld(SOURCE_GROUP)

    group = find_first(data, "Group")

    if not group:
        raise Exception("Group node not found")

    return (
        group.get("description", ""),
        group.get("abstract", "")
    )


def publish_group(
    group_id,
    title,
    description,
    abstract,
    api_key
):

    group_id = group_id.strip("/")

    target_group_uri = (
        f"{TARGET_BASE}/{group_id}"
    )

    payload = {
        "@context": (
            "https://databus.dbpedia.org/"
            "res/context.jsonld"
        ),
        "@graph": {
            "@type": "Group",
            "@id": target_group_uri,
            "title": title,
            "description": description,
            "abstract": abstract
        }
    }

    print("\n===== PUBLISH GROUP =====")
    print("TARGET GROUP:", target_group_uri)

    publish(
        payload,
        api_key
    )


# =========================================================
# ARTIFACTS
# =========================================================

def query_artifacts():

    query = f"""
PREFIX databus: <https://dataid.dbpedia.org/databus#>

SELECT DISTINCT ?artifact
WHERE {{
  ?version databus:group <{SOURCE_GROUP}> .
  ?version databus:artifact ?artifact .
}}
"""

    debug(
        "SPARQL ARTIFACTS",
        {
            "query": query
        }
    )

    r = requests.post(
        SPARQL_ENDPOINT,
        data={
            "query": query
        },
        headers={
            "accept": "application/sparql-results+json"
        }
    )

    print("→ STATUS:", r.status_code)

    if r.status_code >= 400:

        print("❌ RESPONSE:", r.text)
        r.raise_for_status()

    data = r.json()

    return [
        binding["artifact"]["value"]
        for binding in data["results"]["bindings"]
    ]


def publish_artifact(
    group_id,
    artifact_uri,
    api_key
):

    data = fetch_jsonld(artifact_uri)

    artifact = find_first(
        data,
        "Artifact"
    )

    if not artifact:
        raise Exception(
            f"Artifact node missing: {artifact_uri}"
        )

    artifact_id = (
        artifact_uri
        .rstrip("/")
        .split("/")[-1]
    )

    target_id = (
        f"{TARGET_BASE}/"
        f"{group_id}/"
        f"{artifact_id}"
    )

    payload = {
        "@context": (
            "https://databus.dbpedia.org/"
            "res/context.jsonld"
        ),
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
    artifact_uri,
    graph
):

    query = f"""
PREFIX databus: <https://dataid.dbpedia.org/databus#>
PREFIX databus-cv: <https://dataid.dbpedia.org/databus-cv#>
PREFIX dcat: <http://www.w3.org/ns/dcat#>

SELECT DISTINCT ?version
WHERE {{
  ?version databus:group <{SOURCE_GROUP}> .
  ?version databus:artifact <{artifact_uri}> .
  ?version dcat:distribution ?distribution .
  ?distribution databus-cv:graph "{graph}" .
}}
ORDER BY ?version
"""

    debug(
        "SPARQL VERSIONS",
        {
            "graph": graph,
            "query": query
        }
    )

    r = requests.post(
        SPARQL_ENDPOINT,
        data={
            "query": query
        },
        headers={
            "accept": "application/sparql-results+json"
        }
    )

    print("→ STATUS:", r.status_code)

    if r.status_code >= 400:

        print("❌ RESPONSE:", r.text)
        r.raise_for_status()

    data = r.json()

    return [
        binding["version"]["value"]
        for binding in data["results"]["bindings"]
    ]


# =========================================================
# PART GRAPH MATCHING
# =========================================================

def part_matches_graph(part, graph):

    part_graph = part.get("dcv:graph")

    if part_graph is None:
        return False

    # Usually this is simply:
    #
    #   "dbpedia-org"
    #
    # but support JSON-LD values represented
    # as dictionaries as well.

    if isinstance(part_graph, dict):

        value = (
            part_graph.get("@value")
            or part_graph.get("@id")
        )

        return value == graph

    if isinstance(part_graph, list):

        for value in part_graph:

            if isinstance(value, dict):

                value = (
                    value.get("@value")
                    or value.get("@id")
                )

            if value == graph:
                return True

        return False

    return part_graph == graph


# =========================================================
# VERSION + PARTS
# =========================================================

def publish_version(
    group_id,
    artifact_id,
    version_uri,
    graph,
    api_key
):

    print("\n----------------------------------------")
    print("SOURCE VERSION:", version_uri)
    print("GRAPH FILTER:", graph)
    print("----------------------------------------")

    data = fetch_jsonld(version_uri)

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
            f"Version node missing: {version_uri}"
        )

    version_number = (
        version.get("hasVersion")
        or version_uri
        .rstrip("/")
        .split("/")[-1]
    )

    version_id = (
        f"{TARGET_BASE}/"
        f"{group_id}/"
        f"{artifact_id}/"
        f"{version_number}"
    )

    # =====================================================
    # FILTER PARTS BY GRAPH
    # =====================================================

    matching_parts = [
        part
        for part in parts
        if part_matches_graph(
            part,
            graph
        )
    ]

    print(
        f"TOTAL PARTS: {len(parts)}"
    )

    print(
        f"MATCHING PARTS FOR GRAPH "
        f"'{graph}': {len(matching_parts)}"
    )

    if not matching_parts:

        print(
            f"⚠️ No Parts matching graph "
            f"'{graph}' in version:"
        )

        print(version_uri)

        return

    distributions = []

    for part in matching_parts:

        part_id = part.get("@id")

        if not part_id:
            print(
                "⚠️ Skipping Part without @id"
            )
            continue

        fragment = (
            part_id.split("#", 1)[1]
            if "#" in part_id
            else ""
        )

        target_part_id = (
            f"{version_id}#{fragment}"
            if fragment
            else part_id
        )

        dist = {
            "@id": target_part_id,
            "@type": "Part",
            "downloadURL": part.get(
                "downloadURL"
            ),
            "sha256sum": part.get(
                "sha256sum"
            ),
            "dcat:byteSize": part.get(
                "dcat:byteSize"
            )
        }

        # =================================================
        # CONTENT VARIANTS
        # =================================================

        if part.get("dcv:graph") is not None:

            dist["dcv:graph"] = (
                part.get("dcv:graph")
            )

        if part.get("dcv:partition") is not None:

            dist["dcv:partition"] = (
                part.get("dcv:partition")
            )

        if "compression" in part:

            dist["compression"] = (
                part["compression"]
            )

        if "formatExtension" in part:

            dist["formatExtension"] = (
                part["formatExtension"]
            )

        distributions.append(dist)

    if not distributions:

        print(
            "⚠️ No distributions left "
            "after filtering."
        )

        return

    # =====================================================
    # VERSION PAYLOAD
    # =====================================================

    payload = {
        "@context": (
            "https://databus.dbpedia.org/"
            "res/context.jsonld"
        ),
        "@graph": {
            "@type": "Version",
            "@id": version_id,
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
        "\n===== PUBLISH VERSION ====="
    )

    print(
        "TARGET VERSION:",
        version_id
    )

    print(
        "GRAPH:",
        graph
    )

    print(
        "DISTRIBUTIONS:",
        len(distributions)
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
            "Copy DBpedia Databus metadata from "
            "the source group into a target group."
        )
    )

    # Target group ID
    parser.add_argument(
        "group_id",
        help="Target Databus group ID"
    )

    # Target group title
    parser.add_argument(
        "group_title",
        help="Target Databus group title"
    )

    # API key
    parser.add_argument(
        "--api-key",
        required=False,
        help="Databus API key"
    )

    # Graph filter
    parser.add_argument(
        "--graph",
        required=True,
        help=(
            "Only publish versions and Parts "
            "matching this dcv:graph value"
        )
    )

    args = parser.parse_args()

    # =====================================================
    # API KEY
    # =====================================================

    api_key = (
        args.api_key
        or os.getenv("DATABUS_API_KEY")
    )

    if not api_key:

        print(
            "❌ Missing API key"
        )

        sys.exit(1)

    # =====================================================
    # SHOW CONFIGURATION
    # =====================================================

    print("\n################ CONFIGURATION ################")

    print(
        "SOURCE GROUP:",
        SOURCE_GROUP
    )

    print(
        "TARGET GROUP ID:",
        args.group_id
    )

    print(
        "TARGET GROUP TITLE:",
        args.group_title
    )

    print(
        "TARGET GROUP URI:",
        f"{TARGET_BASE}/{args.group_id}"
    )

    print(
        "GRAPH FILTER:",
        args.graph
    )

    print(
        "API KEY: ***REDACTED***"
    )

    # =====================================================
    # GROUP
    # =====================================================

    print("\n################ GROUP ################")

    description, abstract = fetch_group()

    publish_group(
        args.group_id,
        args.group_title,
        description,
        abstract,
        api_key
    )

    # =====================================================
    # ARTIFACTS
    # =====================================================

    print(
        "\n################ ARTIFACTS ################"
    )

    artifacts = query_artifacts()

    print(
        f"\nFOUND {len(artifacts)} ARTIFACTS"
    )

    # =====================================================
    # PROCESS EACH ARTIFACT
    # =====================================================

    for artifact_uri in artifacts:

        try:

            print(
                "\n======================================"
            )

            print(
                "SOURCE ARTIFACT:",
                artifact_uri
            )

            # -------------------------------------------------
            # Publish artifact metadata
            # -------------------------------------------------

            publish_artifact(
                args.group_id,
                artifact_uri,
                api_key
            )

            artifact_id = (
                artifact_uri
                .rstrip("/")
                .split("/")[-1]
            )

            # -------------------------------------------------
            # Find versions matching --graph
            # -------------------------------------------------

            print(
                f"\nQUERYING VERSIONS "
                f"FOR GRAPH '{args.graph}'"
            )

            versions = query_versions(
                artifact_uri,
                args.graph
            )

            print(
                f"FOUND {len(versions)} VERSIONS "
                f"FOR GRAPH '{args.graph}'"
            )

            # -------------------------------------------------
            # Publish matching versions
            # -------------------------------------------------

            for version_uri in versions:

                publish_version(
                    args.group_id,
                    artifact_id,
                    version_uri,
                    args.graph,
                    api_key
                )

        except Exception as e:

            print(
                "\n❌ FAILED:",
                artifact_uri
            )

            print(
                "ERROR:",
                e
            )

    print(
        "\n################ DONE ################"
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()