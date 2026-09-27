#!/usr/bin/env python3
"""The only network-enabled dependency provisioning step. No global installs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {
    "doctest.h": "https://raw.githubusercontent.com/doctest/doctest/v2.4.11/doctest/doctest.h",
    "json.hpp": "https://raw.githubusercontent.com/nlohmann/json/v3.11.3/single_include/nlohmann/json.hpp",
}

def main():
    if sys.version_info < (3, 12):
        raise SystemExit("Use Python 3.12 or newer; 3.12 is the tested interpreter")
    env = ROOT / ".venv"
    if not (env / "bin/python").exists():
        venv.EnvBuilder(with_pip=True).create(env)
    subprocess.run([str(env / "bin/python"), "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.lock")], check=True)
    deps = ROOT / ".deps/include"
    deps.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "dependencies.lock.json"
    expected = json.loads(lock.read_text()) if lock.exists() else {}
    observed = {}
    for name, url in HEADERS.items():
        path = deps / name
        data = path.read_bytes() if path.exists() else urllib.request.urlopen(url, timeout=60).read()
        entry = {"url": url, "sha256": hashlib.sha256(data).hexdigest()}
        if name in expected and entry != expected[name]:
            raise SystemExit(f"Dependency checksum mismatch: {name}")
        path.write_bytes(data)
        observed[name] = entry
    lock.write_text(json.dumps(observed, indent=2) + "\n")
    print("Provisioned pinned dependencies locally. Ordinary builds/tests need no network.")

if __name__ == "__main__":
    main()
