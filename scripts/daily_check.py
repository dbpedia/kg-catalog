#!/usr/bin/env python3
import os
import subprocess
import yaml
from datetime import datetime

# Path to the folder containing all KG folders
KGS_ROOT = os.path.join(os.path.dirname(__file__), "..", "knowledge-graphs")

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def run_daily_check():
    if not os.path.isdir(KGS_ROOT):
        log(f"Knowledge graphs root folder not found: {KGS_ROOT}")
        return

    for kg_name in os.listdir(KGS_ROOT):
        kg_path = os.path.join(KGS_ROOT, kg_name)
        if not os.path.isdir(kg_path):
            continue

        metadata_file = os.path.join(kg_path, "metadata.yaml")
        if not os.path.isfile(metadata_file):
            log(f"No metadata.yaml found in {kg_name}, skipping.")
            continue

        try:
            with open(metadata_file, "r") as f:
                metadata = yaml.safe_load(f)
        except Exception as e:
            log(f"Error reading {metadata_file}: {e}")
            continue

        if metadata.get("metadata-source"):
            importer = os.path.join(os.path.dirname(__file__), "import_rdf_metadata.py")
            log(f"Importing RDF metadata for {kg_name}...")
            try:
                subprocess.run(["python3", importer, metadata_file], check=True)
            except subprocess.CalledProcessError as e:
                log(f"Error importing RDF metadata for {kg_name}: {e}")
            continue

        script_name = metadata.get("check-new-release")
        if not script_name:
            log(f"No 'check-new-release' script for {kg_name}, skipping.")
            continue

        script_path = os.path.join(kg_path, script_name)
        if not os.path.isfile(script_path):
            log(f"Referenced script not found: {script_path}, skipping.")
            continue

        log(f"Running {script_name} for {kg_name}...")
        try:
            subprocess.run(["python3", script_path], check=True)
            log(f"Finished {script_name} for {kg_name}.")
        except subprocess.CalledProcessError as e:
            log(f"Error running {script_path}: {e}")

if __name__ == "__main__":
    run_daily_check()
