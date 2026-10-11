import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml


body = os.environ.get("ISSUE_BODY", "")

errors = []
warnings = []


def get_field(name):
    pattern = rf"### {re.escape(name)}\s*\n\s*(.*?)(?=\n### |\Z)"

    match = re.search(
        pattern,
        body,
        re.S
    )

    if match:
        value = match.group(1).strip()

        if value == "_No response_":
            return None

        return value

    return None


def clean_yaml(text):
    """
    Remove Markdown YAML fences.
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


def valid_url(value):

    if not value:
        return False

    try:

        result = urlparse(value)

        return (
            result.scheme in ("http", "https")
            and result.netloc
        )

    except Exception:

        return False


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


def add_error(message):
    errors.append(message)


def add_warning(message):
    warnings.append(message)


def kg_id_exists(kg_id):
    """
    Check if KG metadata already exists.
    """

    if not kg_id:
        return False

    metadata_file = (
        Path("kgs")
        / kg_id
        / "metadata.yaml"
    )

    return metadata_file.exists()


# --------------------------------------------------
# Extract fields
# --------------------------------------------------

kg_id = get_field("KG ID")

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

keywords = get_field(
    "Keywords"
)

sparql_url = (
    get_field("SPARQL Endpoint URL")
    or get_field("SPARQL Endpoint URLs")
    or get_field("SPARQL Endpoints")
)

artifacts_text = get_field(
    "KG Content (Artifacts, Versions and Distributions)"
)


# --------------------------------------------------
# KG ID
# --------------------------------------------------

if not kg_id:

    add_error(
        "KG ID is missing."
    )

elif not re.match(
    r"^[a-z0-9-]+$",
    kg_id
):

    add_error(
        "KG ID must contain only lowercase letters, numbers and hyphens."
    )

elif kg_id_exists(kg_id):

    add_error(
        f"KG ID '{kg_id}' already exists in the catalog."
    )


# --------------------------------------------------
# Title
# --------------------------------------------------

if not title:

    add_error(
        "KG Title is missing."
    )


# --------------------------------------------------
# Abstract
# --------------------------------------------------

if not abstract:

    add_error(
        "Abstract is missing."
    )

elif len(abstract) > 300:

    add_error(
        "Abstract exceeds maximum length of 300 characters."
    )


# --------------------------------------------------
# Description
# --------------------------------------------------

if not description:

    add_error(
        "Description is missing."
    )


# --------------------------------------------------
# License
# --------------------------------------------------

if not license_url:

    add_error(
        "License is missing."
    )

elif not valid_url(license_url):

    add_error(
        f"License is not a valid URL: {license_url}"
    )


# --------------------------------------------------
# Homepage
# --------------------------------------------------

if homepage:

    homepage = homepage.strip()

    if not valid_url(homepage):

        add_error(
            f"Homepage is not a valid URL: {homepage}"
        )


# --------------------------------------------------
# Domain
# --------------------------------------------------

allowed_domains = [

    "Cross-domain",

    "Geography & Environment",

    "Government & Public Sector",

    "Life Sciences & Health",

    "Economy, Industry & Infrastructure",

    "Publications, Education & Research",

    "Media, Culture & Entertainment",

    "Linguistics, Social & Digital Knowledge Systems",

]


if domain not in allowed_domains:

    add_error(
        f"Invalid domain: {domain}"
    )


# --------------------------------------------------
# Keywords
# --------------------------------------------------

if not keywords:

    add_error(
        "Keywords are missing."
    )

else:

    keyword_list = [

        x.strip()

        for x in keywords.split(",")

        if x.strip()

    ]


    if len(keyword_list) < 3:

        add_error(
            "At least 3 keywords are required."
        )


    if len(keyword_list) > 8:

        add_error(
            "Maximum 8 keywords are allowed."
        )


# --------------------------------------------------
# SPARQL endpoint(s)
# --------------------------------------------------

if sparql_url:
    endpoints = parse_sparql_endpoints(sparql_url)
    if not endpoints:
        add_error(
            f"SPARQL endpoint is invalid: {sparql_url}"
        )
    else:
        for ep in endpoints:
            ep_url = ep.get("url") if isinstance(ep, dict) else (ep if isinstance(ep, str) else None)
            if not ep_url or not valid_url(ep_url):
                add_error(
                    f"SPARQL endpoint URL is invalid: {ep_url or ep}"
                )


# --------------------------------------------------
# Artifacts
# --------------------------------------------------

if not artifacts_text:

    add_error(
        "Artifacts section is missing."
    )

else:

    try:

        artifacts_text = clean_yaml(
            artifacts_text
        )

        artifacts = yaml.safe_load(
            artifacts_text
        )


        if not isinstance(
            artifacts,
            list
        ):

            add_error(
                "Artifacts must be a YAML list."
            )


        else:

            for i, artifact in enumerate(artifacts):

                prefix = f"Artifact #{i+1}"


                if not isinstance(
                    artifact,
                    dict
                ):

                    add_error(
                        f"{prefix}: invalid YAML object."
                    )

                    continue


                if "artifact" not in artifact:

                    add_error(
                        f"{prefix}: missing artifact id."
                    )


                if "title" not in artifact:

                    add_error(
                        f"{prefix}: missing title."
                    )


                versions = artifact.get(
                    "versions"
                )


                if not versions:

                    add_error(
                        f"{prefix}: no versions defined."
                    )

                    continue


                for j, version in enumerate(versions):

                    vp = (
                        f"{prefix}, version #{j+1}"
                    )


                    if "version" not in version:

                        add_error(
                            f"{vp}: missing version."
                        )


                    if "license" not in version:

                        add_error(
                            f"{vp}: missing license."
                        )


                    distributions = version.get(
                        "distributions"
                    )


                    if not distributions:

                        add_error(
                            f"{vp}: no distributions."
                        )

                        continue


                    for k, dist in enumerate(distributions):

                        dp = (
                            f"{vp}, distribution #{k+1}"
                        )


                        if "file" not in dist:

                            add_error(
                                f"{dp}: missing file."
                            )


                        elif not valid_url(
                            dist["file"]
                        ):

                            add_error(
                                f"{dp}: invalid file URL."
                            )


                        if "format" not in dist:

                            add_error(
                                f"{dp}: missing format."
                            )


    except yaml.YAMLError as e:

        add_error(
            f"Artifacts YAML is invalid: {e}"
        )


# --------------------------------------------------
# Create validation result
# --------------------------------------------------

if errors:

    status = "failure"

    result = """
## ❌ KG Metadata Validation Failed

The submission contains the following problems.
Please edit the contents of issue above and save.
Soon you will be notified about the status of the validation.

"""

    for error in errors:

        result += f"- {error}\n"


else:

    status = "success"

    result = """
## ✅ KG Metadata Validation Passed

The submitted Knowledge Graph metadata has successfully completed all validation checks.

All required fields are present and correctly formatted.

A pull request will now be created for review. Once approved and merged, the Knowledge Graph will be added to the KG Catalog ([https://kg-catalog.dbpedia.org/](https://kg-catalog.dbpedia.org/)).

Thank you for your contribution!
"""


if warnings:

    result += "\n### Warnings:\n"

    for warning in warnings:

        result += f"- {warning}\n"


# --------------------------------------------------
# GitHub Actions outputs
# --------------------------------------------------

github_output = os.environ.get(
    "GITHUB_OUTPUT"
)


if github_output:

    with open(
        github_output,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"status={status}\n"
        )

        f.write(
            f"title={title}\n"
        )

        f.write(
            "message<<EOF\n"
        )

        f.write(
            result
        )

        f.write(
            "\nEOF\n"
        )


# Show result in workflow logs

print(result)
