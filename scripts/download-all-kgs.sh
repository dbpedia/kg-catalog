#!/usr/bin/env bash
# Download latest artifacts from every DBpedia KG Catalog Databus group.
# Does not recursively follow arbitrary dataset links inside metadata.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/kg-catalog-download-test}"
VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv-kg-catalog}"
UV_BIN="$SCRIPT_DIR/.kg-catalog-tools/bin/uv"
VAULT_TOKEN_FILE="$SCRIPT_DIR/vault-token.dat"
MAX_SECONDS="${MAX_SECONDS:-172800}"       # per KG, default 48 hours; 0 = unlimited
DISCOVERY_TIMEOUT="${DISCOVERY_TIMEOUT:-45}"
MAX_KGS="${MAX_KGS:-0}"                  # 0 = all
PARALLEL_DOWNLOADS="${PARALLEL_DOWNLOADS:-3}"
GROUPS_FILE="${GROUPS_FILE:-}"
USER_AGENT="${USER_AGENT:-DBpedia-Databus-Python-Client/1.0.0 (https://github.com/dbpedia/databus-python-client)}"

for name in MAX_SECONDS DISCOVERY_TIMEOUT MAX_KGS PARALLEL_DOWNLOADS; do
  if ! [[ "${!name}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: $name must be a non-negative integer" >&2; exit 2
  fi
done
if (( PARALLEL_DOWNLOADS < 1 || DISCOVERY_TIMEOUT < 1 )); then
  echo "ERROR: PARALLEL_DOWNLOADS and DISCOVERY_TIMEOUT must be >= 1" >&2; exit 2
fi

if [ ! -x "$UV_BIN" ]; then
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  else
    command -v curl >/dev/null 2>&1 || { echo 'ERROR: curl is required to install uv' >&2; exit 2; }
    echo 'Installing uv locally (one time)...'
    mkdir -p "$SCRIPT_DIR/.kg-catalog-tools/bin"
    installer="$(mktemp)"
    trap 'rm -f "$installer"' EXIT
    curl --fail --location --show-error --silent --max-time 90 \
      https://astral.sh/uv/install.sh -o "$installer"
    env UV_UNMANAGED_INSTALL="$SCRIPT_DIR/.kg-catalog-tools/bin" sh "$installer"
    rm -f "$installer"
    trap - EXIT
  fi
fi
if [ ! -x "$VENV_DIR/bin/python" ] || ! "$VENV_DIR/bin/python" -c \
    'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
  echo 'Creating isolated Python 3.11 environment...'
  "$UV_BIN" venv --python 3.11 --managed-python --allow-existing "$VENV_DIR"
fi
if [ ! -x "$VENV_DIR/bin/databusclient" ]; then
  echo 'Installing Databus Python Client 1.0.0...'
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" 'databusclient==1.0.0'
fi

if [ -e "$VAULT_TOKEN_FILE" ]; then
  if [ ! -f "$VAULT_TOKEN_FILE" ] || [ ! -r "$VAULT_TOKEN_FILE" ] || [ ! -s "$VAULT_TOKEN_FILE" ]; then
    echo "ERROR: vault-token.dat exists but is not a readable, nonempty file" >&2; exit 2
  fi
  echo 'Vault token file detected; authenticated downloads enabled.'
else
  echo 'No vault-token.dat; unauthenticated downloads.'
fi
mkdir -p "$OUTPUT_DIR/downloads" "$OUTPUT_DIR/reports"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"

# The client uses requests for downloads but does not expose a --user-agent CLI
# option. sitecustomize is imported automatically by each Python process and
# sets the User-Agent on its requests.Session requests (including HEAD and GET).
HOOK_DIR="$SCRIPT_DIR/.kg-catalog-tools/python-hooks"
mkdir -p "$HOOK_DIR"
cat > "$HOOK_DIR/sitecustomize.py" <<'PYHOOK'
import os

agent = os.environ.get("KG_DATABUS_USER_AGENT", "")
if agent:
    try:
        import requests
        original_request = requests.sessions.Session.request

        def request_with_user_agent(self, method, url, **kwargs):
            headers = dict(kwargs.get("headers") or {})
            headers["User-Agent"] = agent
            kwargs["headers"] = headers
            return original_request(self, method, url, **kwargs)

        requests.sessions.Session.request = request_with_user_agent
    except ImportError:
        pass
PYHOOK

export OUTPUT_DIR MAX_SECONDS DISCOVERY_TIMEOUT MAX_KGS PARALLEL_DOWNLOADS GROUPS_FILE VAULT_TOKEN_FILE
export CLIENT_BIN="$VENV_DIR/bin/databusclient"
export KG_DATABUS_USER_AGENT="$USER_AGENT"
export PYTHONPATH="$HOOK_DIR${PYTHONPATH:+:$PYTHONPATH}"

echo "Python: $($VENV_DIR/bin/python --version)"
echo "Databus client: $CLIENT_BIN"
echo "User-Agent: $USER_AGENT"
echo "Timeout per KG: ${MAX_SECONDS}s (0 = unlimited)"
echo "Parallel downloads: $PARALLEL_DOWNLOADS"
echo "Output: $OUTPUT_DIR"

"$VENV_DIR/bin/python" - <<'PY' &
import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse, request

base = "https://databus.dbpedia.org/knowledge-graph-catalog/"
endpoint = "https://databus.dbpedia.org/sparql"
account = base.rstrip("/")
out = Path(os.environ["OUTPUT_DIR"])
client = os.environ["CLIENT_BIN"]
max_seconds = int(os.environ["MAX_SECONDS"])
discovery_timeout = int(os.environ["DISCOVERY_TIMEOUT"])
max_kgs = int(os.environ["MAX_KGS"])
parallel = int(os.environ["PARALLEL_DOWNLOADS"])
groups_file = os.environ["GROUPS_FILE"]
vault_file = Path(os.environ["VAULT_TOKEN_FILE"])
agent = os.environ["KG_DATABUS_USER_AGENT"]
runid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
report = out / "reports" / f"{runid}.csv"
stop = threading.Event()
active = {}
active_lock = threading.Lock()
print_lock = threading.Lock()
fields = ["kg", "group_url", "status", "selected_files", "succeeded", "failed", "bytes", "error", "log", "manifest"]


def say(message):
    with print_lock:
        print(message, flush=True)


def terminate_process(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def on_signal(sig, frame):
    stop.set()
    say(f"Received signal {sig}: stopping active downloads...")
    with active_lock:
        running = list(active.values())
    for proc in running:
        terminate_process(proc)


signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)


def discover():
    if groups_file:
        urls = [line.strip() for line in Path(groups_file).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    else:
        query = f"""PREFIX databus: <https://dataid.dbpedia.org/databus#>
SELECT DISTINCT ?group WHERE {{
  ?group a databus:Group ;
         databus:account <{account}> .
}}
ORDER BY ?group"""
        body = parse.urlencode({"query": query}).encode("utf-8")
        req = request.Request(endpoint, data=body, headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": agent,
        })
        say("Discovering KG groups through Databus SPARQL...")
        with request.urlopen(req, timeout=discovery_timeout) as response:
            result = json.load(response)
        urls = [item["group"]["value"] for item in result["results"]["bindings"]]
    valid = set()
    for uri in urls:
        uri = uri.rstrip("/")
        if uri.startswith(base) and len(uri[len(base):].split("/")) == 1 and uri[len(base):]:
            valid.add(uri)
    ordered = sorted(valid)
    return ordered[:max_kgs] if max_kgs else ordered


def process_group(index, total_groups, group):
    kg = group.rsplit("/", 1)[-1]
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", kg)
    prefix = f"{runid}-{safe}"
    logpath = out / "reports" / f"{prefix}.log"
    manifestpath = out / "reports" / f"{prefix}.jsonld"
    dest = out / "downloads" / safe
    row = dict(kg=kg, group_url=group, status="CANCELLED", selected_files=0,
               succeeded=0, failed=0, bytes=0, error="Cancelled before start",
               log=str(logpath), manifest=str(manifestpath))
    if stop.is_set():
        return index, row

    dest.mkdir(parents=True, exist_ok=True)
    cmd = [client, "download", group, "--localdir", str(dest),
           "--validate-checksum", "--manifest", str(manifestpath)]
    if vault_file.is_file():
        cmd += ["--vault-token", str(vault_file)]
    say(f"[{index}/{total_groups}] {kg}: downloading...")
    rc = -1
    error = ""
    cancelled = False
    with logpath.open("w", encoding="utf-8") as log:
        try:
            # One process group per client. A controller signal can stop them all.
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            with active_lock:
                active[index] = proc
            if stop.is_set():
                terminate_process(proc)
            try:
                rc = proc.wait(timeout=max_seconds if max_seconds else None)
            except subprocess.TimeoutExpired:
                error = f"Timed out after {max_seconds}s"
                terminate_process(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            cancelled = stop.is_set()
        except Exception as exc:
            error = str(exc)
        finally:
            with active_lock:
                active.pop(index, None)

    totals = {"dbus:totalFiles": 0, "dbus:succeeded": 0, "dbus:failed": 0, "dbus:totalBytes": 0}
    if manifestpath.is_file():
        try:
            totals.update(json.loads(manifestpath.read_text(encoding="utf-8")).get("dbus:executionResult", {}))
        except (OSError, ValueError, TypeError) as exc:
            error = error or f"Invalid manifest: {exc}"
    else:
        error = error or "Missing manifest"

    total = int(totals.get("dbus:totalFiles") or 0)
    success = int(totals.get("dbus:succeeded") or 0)
    bad = int(totals.get("dbus:failed") or 0)
    size = int(totals.get("dbus:totalBytes") or 0)
    ok = rc == 0 and total > 0 and success == total and bad == 0 and not error and not cancelled
    if cancelled:
        status = "CANCELLED"
        error = "Stopped by user"
    elif ok:
        status = "PASS"
    else:
        status = "FAIL"
        error = error or f"rc={rc}, selected={total}, success={success}, failed={bad}"
    row.update(status=status, selected_files=total, succeeded=success,
               failed=bad, bytes=size, error=error)
    return index, row


try:
    groups = discover()
except Exception as exc:
    say(f"FAIL: Could not discover groups: {exc}")
    sys.exit(2)
if not groups:
    say("FAIL: No KG groups discovered")
    sys.exit(2)
say(f"Discovered KG groups: {len(groups)}")
say(f"Report: {report}")
passed = failed = cancelled_count = 0
with report.open("w", newline="", encoding="utf-8") as fp:
    writer = csv.DictWriter(fp, fieldnames=fields)
    writer.writeheader()
    fp.flush()
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(process_group, i, len(groups), group)
                   for i, group in enumerate(groups, 1)]
        for future in as_completed(futures):
            try:
                index, row = future.result()
            except Exception as exc:
                say(f"Unexpected worker failure: {exc}")
                failed += 1
                continue
            writer.writerow(row)
            fp.flush()
            passed += row["status"] == "PASS"
            failed += row["status"] == "FAIL"
            cancelled_count += row["status"] == "CANCELLED"
            detail = f" - {row['error']}" if row["error"] else ""
            say(f"[{index}/{len(groups)}] {row['kg']}: {row['status']} "
                f"({row['succeeded']}/{row['selected_files']} files){detail}")
say(f"Finished: {passed} PASS; {failed} FAIL; {cancelled_count} CANCELLED; {len(groups)} total")
say(f"CSV report: {report}")
sys.exit(130 if stop.is_set() else (1 if failed else 0))
PY
controller_pid=$!
trap 'kill -TERM "$controller_pid" 2>/dev/null || true' INT TERM
rc=0
wait "$controller_pid" || rc=$?
trap - INT TERM
exit "$rc"