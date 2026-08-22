"""
auto_updater.py - Automated offset synchronization engine for Luqqzstrap.

Monitors official Roblox deployment channels and high-speed offset mirrors.
Produces validated, standardized FFlags.hpp and FFlags.json files for Luqqzstrap.
Designed to run in GitHub Actions (every 10-15 minutes) and standalone.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# Roblox deployment API
ROBLOX_VERSION_URL = "https://clientsettings.roblox.com/v2/client-version/WindowsPlayer"
ROBLOX_SETTINGS_URL = "https://clientsettingscdn.roblox.com/v2/settings/application/PCDesktopClient"

# Fast offset sources
SOURCES = [
    ("imtheo_dev", "https://dev.imtheo.lol/Offsets/FFlags.hpp"),
    ("imtheo_stable", "https://offsets.imtheo.lol/FFlags.hpp"),
    ("workers_dev", "https://offsets.ntgetwritewatch.workers.dev/FFlags.hpp"),
    ("github_mirror", "https://raw.githubusercontent.com/4anti/Roblox-Fastflag-Manager/main/data/FFlags.hpp"),
]

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "src" / "data"
PUBLIC_DATA_DIR = ROOT / "data"


def fetch_url(url: str, timeout: int = 10) -> bytes | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"[-] Failed to fetch {url}: {e}")
        return None


def get_current_roblox_live_version() -> str | None:
    raw = fetch_url(ROBLOX_VERSION_URL)
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
        return data.get("clientVersionUpload")
    except Exception as e:
        print(f"[-] Error parsing Roblox live version: {e}")
        return None


def extract_version_from_hpp(body: bytes) -> str | None:
    # 1. Check embedded ClientVersion = "version-xxxx"
    m = re.search(rb'ClientVersion\s*=\s*"([^"]+)"', body)
    if m:
        return m.group(1).decode("ascii", errors="ignore")
    # 2. Check header comment: /* Roblox Version : version-xxxx
    m = re.search(rb'Roblox Version\s*:\s*(version-[0-9a-fA-F]+)', body)
    if m:
        return m.group(1).decode("ascii", errors="ignore")
    return None


def validate_and_format_hpp(body: bytes, target_version: str | None = None) -> bytes | None:
    # Validate minimum size and basic markers
    if len(body) < 100000 or b"FFlag" not in body:
        return None
    
    extracted_version = extract_version_from_hpp(body)
    version_to_use = extracted_version or target_version or "version-unknown"

    # Ensure clean header
    lines = body.decode("utf-8", errors="ignore").splitlines()
    cleaned_lines = []
    has_pragma = False
    
    for line in lines:
        if line.strip() == "#pragma once":
            has_pragma = True
            cleaned_lines.append("#pragma once")
            continue
        cleaned_lines.append(line)
        
    if not has_pragma:
        cleaned_lines.insert(0, "#pragma once")
        
    content = "\n".join(cleaned_lines).encode("utf-8")
    return content


def sync_offsets():
    print("[*] Starting Luqqzstrap Offset Synchronization...")
    live_version = get_current_roblox_live_version()
    print(f"[*] Current Roblox LIVE channel build: {live_version}")

    best_body: bytes | None = None
    best_source: str | None = None
    best_version: str | None = None

    for sid, url in SOURCES:
        print(f"[*] Probing source: {sid} ({url})...")
        raw = fetch_url(url)
        if not raw:
            continue
            
        v = extract_version_from_hpp(raw)
        print(f"[+] Source {sid} returned version: {v} (size: {len(raw)} bytes)")
        
        # If this source matches the exact live Roblox version, choose it immediately
        if live_version and v == live_version:
            best_body = raw
            best_source = sid
            best_version = v
            print(f"[+] Found PERFECT match for live version {live_version} from {sid}!")
            break
            
        # Otherwise keep the first valid source as fallback
        if best_body is None and len(raw) > 500000:
            best_body = raw
            best_source = sid
            best_version = v

    if not best_body:
        print("[-] No valid offset source responded.")
        return False

    formatted = validate_and_format_hpp(best_body, best_version or live_version)
    if not formatted:
        print("[-] Offset validation failed.")
        return False

    # Target output paths
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)

    dest_files = [
        DATA_DIR / "FFlags_baseline.hpp",
        PUBLIC_DATA_DIR / "FFlags.hpp",
    ]

    updated = False
    for path in dest_files:
        existing = path.read_bytes() if path.exists() else b""
        if existing != formatted:
            path.write_bytes(formatted)
            print(f"[+] Written updated offsets to {path} ({len(formatted)} bytes)")
            updated = True
        else:
            print(f"[*] {path} is already up to date.")

    # Also compress baseline for runtime packaging
    gz_path = DATA_DIR / "FFlags_baseline.hpp.gz"
    with gzip.open(gz_path, "wb") as f:
        f.write(formatted)
    print(f"[+] Compressed baseline saved to {gz_path}")

    # Fetch live PCDesktopClient JSON
    print("[*] Fetching latest PCDesktopClient flag definitions...")
    pc_data = fetch_url(ROBLOX_SETTINGS_URL)
    if pc_data:
        try:
            parsed = json.loads(pc_data.decode("utf-8"))
            settings = parsed.get("applicationSettings", {})
            if len(settings) > 10000:
                json_path = DATA_DIR / "PCDesktopClient.json"
                gz_json_path = DATA_DIR / "PCDesktopClient.json.gz"
                
                json_bytes = json.dumps(settings, indent=4).encode("utf-8")
                json_path.write_bytes(json_bytes)
                with gzip.open(gz_json_path, "wb") as f:
                    f.write(json_bytes)
                print(f"[+] Saved {len(settings)} flags to {json_path} and {gz_json_path}")
        except Exception as e:
            print(f"[!] Warning: Could not update PCDesktopClient.json: {e}")

    print(f"\n[+] Sync Complete! Version: {best_version} | Source: {best_source}")
    return updated


if __name__ == "__main__":
    sync_offsets()
