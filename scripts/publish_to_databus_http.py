import yaml
import requests
import os
import sys
import json
import hashlib

# --- Config ---
API_PUBLISH = "https://databus.dbpedia.org/api/publish?fetch-file-properties=false"

yaml_file = sys.argv[1]


# --- Helpers ---
def calculate_sha256(url):
    """Downloads file in chunks to calculate sha256."""

    headers = {
        "User-Agent": "KG-Catalog/1.0 (https://github.com/dbpedia/kg-catalog)"
    }

    h = hashlib.sha256()
    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                h.update(chunk)
    return h.hexdigest()


def fetch_size(url):
    """
    Fetch file size using HTTP HEAD request (Content-Length).
    Returns int or None if unavailable.
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        r.raise_for_status()

        size = r.headers.get("Content-Length")
        if size is not None:
            return int(size)

        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()

        size = r.headers.get("Content-Length")
        if size is not None:
            return int(size)

    except Exception as e:
        print(f"⚠️ Could not fetch size for {url}: {e}")

    return None


# --- Load YAML ---
try:
    with open(yaml_file, "r") as f:
        data = yaml.safe_load(f)
except yaml.YAMLError as e:
    print(f"❌ YAML format error: {e}")
    sys.exit(1)

if not data:
    print(f"No data loaded from {yaml_file}")
    sys.exit(1)


# --- Auth ---
databus_account = data.get("databus-account")
if not databus_account:
    raise ValueError("databus-account is not specified in metadata.yaml")

api_key_env = databus_account.upper().replace("-", "_")
API_KEY = os.environ.get(api_key_env)

if not API_KEY:
    print("Error: DATABUS_API_KEY not set")
    sys.exit(1)


# --- Publish flag ---
if not data.get("databus-publish", False):
    print(f"Skipping {yaml_file}: databus-publish is false")
    sys.exit(0)


# --- Publisher ---
def send_publish(payload):
    print("=== Payload to publish ===")
    print(json.dumps(payload, indent=2))
    print("=========================")

    headers = {
        "accept": "application/json",
        "Content-Type": "application/ld+json",
        "X-API-KEY": API_KEY
    }

    resp = requests.post(API_PUBLISH, headers=headers, json=payload)

    if not resp.ok:
        print("=== Databus error response ===")
        print(resp.status_code)
        print(resp.text)
        print("==============================")

    resp.raise_for_status()
    return resp.json()


# --- Step 1: Group ---
group_id = f"https://databus.dbpedia.org/{databus_account}/{data['id']}"

send_publish({
    "@context": "https://databus.dbpedia.org/res/context.jsonld",
    "@graph": {
        "@id": group_id,
        "@type": "Group",
        "title": data["title"],
        "abstract": data.get("abstract", ""),
        "description": data.get("description", "")
    }
})

print(f"✅ Published group: {group_id}")


# --- Step 2: Artifacts & Versions ---
for artifact in data.get("artifacts", []):
    artifact_id = f"{group_id}/{artifact['artifact'].replace(' ', '-')}"

    send_publish({
        "@context": "https://databus.dbpedia.org/res/context.jsonld",
        "@graph": {
            "@id": artifact_id,
            "@type": "Artifact",
            "title": artifact["title"],
            "abstract": artifact.get("abstract", ""),
            "description": artifact.get("description", "")
        }
    })

    print(f"✅ Published artifact: {artifact_id}")

    for version in artifact.get("versions", []):
        version_str = str(version["version"])
        version_id = f"{artifact_id}/{version_str.replace(' ', '-')}"

        dist_list = []

        for i, dist in enumerate(version.get("distributions", []), start=1):
            part_id = f"{version_id}#e{i}"
            file_url = dist.get("file")

            if not file_url:
                raise ValueError(f"Missing file URL for distribution {part_id}")

            # --- SHA256 ---
            sha256 = dist.get("sha256")
            if not sha256:
                print(f"⚠️ Missing sha256 for {file_url}, computing...")
                sha256 = calculate_sha256(file_url)
                dist["sha256"] = sha256  # ✅ UPDATE YAML IN MEMORY

            # --- SIZE ---
            size = dist.get("size")
            if not size:
                print(f"⚠️ Missing size for {file_url}, fetching via HEAD...")
                size = fetch_size(file_url)

            if not size:
                print(f"⚠️ Size still unavailable for {file_url}, defaulting to 1")
                size = 1

            dist["size"] = size  # ✅ UPDATE YAML IN MEMORY

            part = {
                "@id": part_id,
                "@type": "Part",
                "formatExtension": dist.get("format"),
                "compression": dist.get("compression", "none"),
                "sha256sum": sha256,
                "dcat:byteSize": size,
                "downloadURL": file_url
            }
            
            dist_list.append(part)

        version_payload = {
            "@context": "https://databus.dbpedia.org/res/context.jsonld",
            "@graph": {
                "@type": "Version",
                "@id": version_id,
                "title": version["title"],
                "abstract": version.get("abstract", ""),
                "description": version.get("description", ""),
                "license": version.get(
                    "license",
                    "https://creativecommons.org/licenses/by/4.0/"
                ),
                "distribution": dist_list
            }
        }

        send_publish(version_payload)
        print(f"✅ Published version: {version_id}")


# --- Reset publish flag ---
data["databus-publish"] = False

with open(yaml_file, "w") as f:
    yaml.dump(data, f, sort_keys=False)

print(f"💾 Updated YAML + reset databus-publish to false for {yaml_file}")
