import os
import sys
import yaml
import requests

API_URL = "https://moss.dev.dbpedia.link/api/v1/save-entry"

yaml_file = sys.argv[1]

# -----------------------
# Load YAML
# -----------------------

try:
    with open(yaml_file, "r") as f:
        data = yaml.safe_load(f)
except yaml.YAMLError as e:
    print(f"❌ YAML format error: {e}")
    sys.exit(1)

if not data:
    print(f"No data loaded from {yaml_file}")
    sys.exit(1)

# -----------------------
# Publish flag
# -----------------------

if not data.get("moss-publish", False):
    print(f"Skipping {yaml_file}: moss-publish is false")
    sys.exit(0)

# -----------------------
# API Key
# -----------------------

API_KEY = os.environ.get("MOSS_KG_CATALOG")

if not API_KEY:
    print("❌ Environment variable MOSS_KG_CATALOG is not set")
    sys.exit(1)

# -----------------------
# Required metadata
# -----------------------

databus_account = data.get("databus-account")
dataset_id = data.get("id")

if not databus_account:
    raise ValueError("Missing databus-account")

if not dataset_id:
    raise ValueError("Missing id")

resource = f"https://databus.dbpedia.org/{databus_account}/{dataset_id}"

# -----------------------
# Optional metadata
# -----------------------

homepage = data.get("homepage")
domains = data.get("domains", [])
keywords = data.get("keywords", [])
sparql = data.get("sparql", [])
maintainers = data.get("maintainers", [])
last_version_size = data.get("last-version-size")

# -----------------------
# Check if anything exists
# -----------------------

if not any([
    homepage,
    domains,
    keywords,
    sparql,
    maintainers,
    last_version_size is not None,
]):
    print(f"⚠️ No publishable metadata for {yaml_file}")

    data["moss-publish"] = False
    with open(yaml_file, "w") as f:
        yaml.dump(data, f, sort_keys=False)

    sys.exit(0)

# -----------------------
# Build Turtle dynamically
# -----------------------

triples = []

triples.append(f"<{resource}> a databus:Group ;")

# homepage
if homepage:
    triples.append(f"    foaf:homepage <{homepage}> ;")

# domains -> dcterms:subject
if domains:
    domain_values = ",\n        ".join(f'"{d}"' for d in domains)
    triples.append(f"    dcterms:subject {domain_values} ;")

# keywords -> schema:keywords
if keywords:
    keyword_values = ",\n        ".join(f'"{k}"' for k in keywords)
    triples.append(f"    schema:keywords {keyword_values} ;")

# SPARQL endpoint(s)
if sparql:
    if isinstance(sparql, str):
        triples.append(f"    void:sparqlEndpoint <{sparql}> ;")
    elif isinstance(sparql, list):
        for entry in sparql:
            if isinstance(entry, dict):
                ep_url = entry.get("url")
            elif isinstance(entry, str):
                ep_url = entry
            else:
                ep_url = None
            if ep_url:
                triples.append(f"    void:sparqlEndpoint <{ep_url}> ;")

# Dataset size
if last_version_size is not None:
    triples.append(f'    dcat:byteSize "{last_version_size}" ;')

# Maintainers
if maintainers:
    for m in maintainers:
        name = m.get("name")
        email = m.get("contact")
        github = m.get("github")

        maintainer_block = [
            "    schema:maintainer [",
            "        a foaf:Person ;"
        ]

        if name:
            maintainer_block.append(f'        foaf:name "{name}" ;')

        if email:
            maintainer_block.append(f'        foaf:mbox <mailto:{email}> ;')

        if github:
            maintainer_block.extend([
                "        foaf:account [",
                "            a foaf:OnlineAccount ;",
                f'            foaf:accountName "{github}" ;',
                "            foaf:accountServiceHomepage <https://github.com/> ;",
                "        ] ;"
            ])

        maintainer_block.append("    ] ;")

        triples.extend(maintainer_block)

# Replace final semicolon with a period
if triples:
    triples[-1] = triples[-1].rstrip(" ;") + " ."

ttl = "\n".join([
    "PREFIX schema: <https://schema.org/>",
    "PREFIX databus: <https://dataid.dbpedia.org/databus#>",
    "PREFIX void: <http://rdfs.org/ns/void#>",
    "PREFIX foaf: <http://xmlns.com/foaf/0.1/>",
    "PREFIX dcterms: <http://purl.org/dc/terms/>",
    "PREFIX dcat: <http://www.w3.org/ns/dcat#>",
    "",
    *triples
])

print("=== Turtle payload ===")
print(ttl)
print("======================")

# -----------------------
# POST to MOSS
# -----------------------

headers = {
    "accept": "application/json",
    "X-API-KEY": API_KEY,
    "Content-Type": "text/turtle",
}

params = {
    "module": "kg-metadata",
    "resource": resource,
}

response = requests.post(
    API_URL,
    params=params,
    headers=headers,
    data=ttl.encode("utf-8"),
    timeout=60,
)

try:
    response.raise_for_status()
except requests.HTTPError:
    print("❌ MOSS API error:")
    print(response.text)
    raise

print(f"✅ Published metadata for {resource}")

# -----------------------
# Reset publish flag
# -----------------------

data["moss-publish"] = False

with open(yaml_file, "w") as f:
    yaml.dump(data, f, sort_keys=False)

print(f"💾 Updated {yaml_file} and reset moss-publish to false")
