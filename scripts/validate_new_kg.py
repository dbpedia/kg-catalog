import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml


body = os.environ.get("ISSUE_BODY", "")

# Databus only accepts version names of at least 3 characters made of
# letters, digits, "_", "." and "-" (see the version SHACL shape in
# https://github.com/dbpedia/databus/blob/main/server/app/common/res/shacl/version.shacl).
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,}$")


class RawFloat(float):
    """
    A float that remembers how it was written in the YAML,
    so we can tell when YAML changed it (e.g. 2.10 -> 2.1).
    """


class VersionLoader(yaml.SafeLoader):
    pass


def construct_raw_float(loader, node):
    value = RawFloat(loader.construct_yaml_float(node))
    value.raw = node.value
    return value


VersionLoader.add_constructor(
    "tag:yaml.org,2002:float",
    construct_raw_float
)

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


def add_error(message):
    errors.append(message)


def add_warning(message):
    warnings.append(message)


def check_version(prefix, value):
    """
    Check that a version name can be published on Databus.
    """

    if value is None or str(value).strip() == "":

        add_error(
            f"{prefix}: missing version."
        )

        return

    if isinstance(value, RawFloat) and str(value) != value.raw:

        add_error(
            f"{prefix}: version {value.raw} is read by YAML as the number "
            f"{value}, so it would be published as \"{value}\". "
            f"Put it in quotes, for example version: \"{value.raw}\"."
        )

        return

    if not VERSION_PATTERN.match(str(value)):

        add_error(
            f"{prefix}: version \"{value}\" is not allowed on Databus. "
            "Use at least 3 characters made of letters, digits, "
            "\"_\", \".\" or \"-\" (for example 2026.10.01 or 2.0)."
        )


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

sparql_url = get_field(
    "SPARQL Endpoint URL"
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
# SPARQL endpoint
# --------------------------------------------------

if sparql_url and not valid_url(sparql_url):

    add_error(
        f"SPARQL endpoint URL is invalid: {sparql_url}"
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

        artifacts = yaml.load(
            artifacts_text,
            Loader=VersionLoader
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

                    else:

                        check_version(
                            vp,
                            version["version"]
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
