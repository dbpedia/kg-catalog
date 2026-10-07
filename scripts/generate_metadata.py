import os
import re
from pathlib import Path

import yaml


body = os.environ.get("ISSUE_BODY", "")


def normalize_value(value):
    """
    Normalize GitHub Issue Form values.

    Converts:
    - "_No response_" -> None
    - empty strings -> None
    """

    if not value:
        return None

    value = value.strip()

    if value == "_No response_":
        return None

    if value == "":
        return None

    return value


def get_field(name):
    """
    Extract GitHub Issue Form field.
    """

    pattern = rf"### {re.escape(name)}\s*\n\s*(.*?)(?=\n### |\Z)"

    match = re.search(
        pattern,
        body,
        re.S
    )

    if match:
        return normalize_value(match.group(1))

    return None


def clean_yaml(text):
    """
    Remove Markdown YAML fences.

    Converts:

    ```yaml
    - artifact: example
    ```

    into pure YAML.
    """

    if not text:
        return text

    text = text.strip()

    if text.startswith("```"):

        lines = text.splitlines()

        if lines[0].strip().startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines)

    return text.strip()


def parse_sparql_endpoints(text):
    """
    Parse SPARQL endpoint field into a list of dicts.
    Accepts single URL, multiple URLs (per line or comma-separated),
    or YAML list of dicts/strings.
    """
    if not text:
        return []

    text = text.strip()
    if not text or text == "_No response_":
        return []

    cleaned = clean_yaml(text)
    if cleaned.startswith("-") or "\n" in cleaned:
        try:
            loaded = yaml.safe_load(cleaned)
            if isinstance(loaded, list):
                endpoints = []
                for i, item in enumerate(loaded):
                    if isinstance(item, dict):
                        endpoints.append(item)
                    elif isinstance(item, str) and item.strip():
                        name = "main" if i == 0 else f"endpoint-{i+1}"
                        endpoints.append({"name": name, "url": item.strip()})
                if endpoints:
                    return endpoints
            elif isinstance(loaded, dict) and "url" in loaded:
                return [loaded]
        except Exception:
            pass

    endpoints = []
    raw_urls = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in line.split(","):
            u = part.strip()
            if u:
                raw_urls.append(u)

    for i, u in enumerate(raw_urls):
        name = "main" if i == 0 else f"endpoint-{i+1}"
        endpoints.append({"name": name, "url": u})

    return endpoints


# --------------------------------------------------
# Extract fields
# --------------------------------------------------

kg_id = get_field(
    "KG ID"
)

title = get_field(
    "KG Title"
)

abstract = get_field(
    "KG Short Abstract"
)

description = get_field(
    "KG Full Description"
)

license_url = get_field(
    "License"
)

homepage = get_field(
    "KG Homepage"
)

domain = get_field(
    "KG Primary Domain"
)

keywords_text = get_field(
    "Keywords"
)

sparql_url = (
    get_field("SPARQL Endpoint URL")
    or get_field("SPARQL Endpoint URLs")
    or get_field("SPARQL Endpoints")
)

maintainer_name = get_field(
    "KG Maintainer Name"
)

maintainer_contact = get_field(
    "KG Maintainer Contact"
)

maintainer_github = get_field(
    "KG Maintainer GitHub Username"
)

artifacts_text = get_field(
    "KG Content (Artifacts, Versions and Distributions)"
)


# --------------------------------------------------
# Validate required fields
# --------------------------------------------------

required_fields = {

    "KG ID":
        kg_id,

    "KG Title":
        title,

    "KG Short Abstract":
        abstract,

    "KG Full Description":
        description,

    "License":
        license_url,

    "KG Homepage":
        homepage,

    "KG Primary Domain":
        domain,

    "Keywords":
        keywords_text,

    "KG Content":
        artifacts_text
}


missing_fields = [

    name
    for name, value in required_fields.items()
    if not value

]


if missing_fields:

    raise ValueError(
        "Missing required fields: "
        + ", ".join(missing_fields)
    )


# --------------------------------------------------
# Parse keywords
# --------------------------------------------------

keywords = [

    x.strip()

    for x in keywords_text.split(",")

    if x.strip()

]


# --------------------------------------------------
# Parse artifacts
# --------------------------------------------------

artifacts = []

if artifacts_text:

    artifacts = yaml.safe_load(
        clean_yaml(
            artifacts_text
        )
    )


    # Ensure every distribution has status: pending

    if artifacts:

        for artifact in artifacts:

            for version in artifact.get(
                "versions",
                []
            ):

                for distribution in version.get(
                    "distributions",
                    []
                ):

                    distribution["status"] = "pending"


# --------------------------------------------------
# Build metadata YAML
# --------------------------------------------------

metadata = {

    "databus-account":
        "knowledge-graph-catalog",

    "id":
        kg_id,

    "title":
        title,

    "abstract":
        abstract,

    "description":
        description,

    "moss-publish":
        True,

    "databus-publish":
        True,

    "license":
        license_url,

    "homepage":
        homepage,

    "domains":
        [
            domain
        ],

    "keywords":
        keywords,

    "artifacts":
        artifacts

}


# --------------------------------------------------
# Optional SPARQL endpoint(s)
# --------------------------------------------------

if sparql_url:
    endpoints = parse_sparql_endpoints(sparql_url)
    if endpoints:
        metadata["sparql"] = endpoints


# --------------------------------------------------
# Optional maintainer
# --------------------------------------------------

if any([

    maintainer_name,

    maintainer_contact,

    maintainer_github

]):

    maintainer = {}


    if maintainer_name:

        maintainer["name"] = maintainer_name


    if maintainer_contact:

        maintainer["contact"] = maintainer_contact


    if maintainer_github:

        maintainer["github"] = maintainer_github


    metadata["maintainers"] = [

        maintainer

    ]


# --------------------------------------------------
# Create output directory
# --------------------------------------------------

output_dir = Path(
    "knowledge-graphs"
) / kg_id


output_dir.mkdir(
    parents=True,
    exist_ok=True
)


output_file = (
    output_dir /
    "metadata.yaml"
)


# --------------------------------------------------
# Write YAML
# --------------------------------------------------

with output_file.open(
    "w",
    encoding="utf-8"
) as f:

    yaml.dump(
        metadata,
        f,
        allow_unicode=True,
        sort_keys=False
    )


print(
    f"Generated {output_file}"
)
