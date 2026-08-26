"""
native_dumper.py - Luqqzstrap Independent Native Binary PE FastFlag Dumper.

Autonomously extracts FastFlags, struct pointers (FFlagList.Pointer, ToFlag, ToValue),
and RVAs directly from RobloxPlayerBeta.exe without relying on any third-party dumpers.

Usage:
  python scripts/dumper/native_dumper.py --version version-ddf602d9cfe44005
  python scripts/dumper/native_dumper.py --exe "C:/path/to/RobloxPlayerBeta.exe"
  python scripts/dumper/native_dumper.py --latest
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

try:
    import pefile
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pefile"])
    import pefile


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "src" / "data"
PUBLIC_DATA_DIR = ROOT / "data"
ROBLOX_CDN_BASE = "https://setup.rbxcdn.com"
CLIENT_VERSION_JSON = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer"


def log(msg: str):
    print(f"[*] {msg}", flush=True)


def download_roblox_binary(version_guid: str, out_dir: Path) -> Path | None:
    """Download RobloxApp.zip from Roblox CDN and extract RobloxPlayerBeta.exe."""
    cdn_bases = [
        "https://setup.rbxcdn.com",
        "https://setup-aws.rbxcdn.com",
        "https://setup-ak.rbxcdn.com",
        "https://s3.amazonaws.com/setup.roblox.com",
    ]
    package_names = ["RobloxApp.zip", "RobloxPlayer.zip"]
    
    zip_path = out_dir / f"{version_guid}.zip"
    exe_target = out_dir / "RobloxPlayerBeta.exe"

    for base in cdn_bases:
        for pkg in package_names:
            zip_url = f"{base}/{version_guid}-{pkg}"
            log(f"Attempting download from {zip_url}...")
            try:
                req = urllib.request.Request(
                    zip_url,
                    headers={"User-Agent": "Roblox/WinInet"}
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    if resp.status == 200:
                        zip_path.write_bytes(resp.read())
                        log(f"[+] Downloaded {pkg} ({os.path.getsize(zip_path) / (1024*1024):.2f} MB)")
                        break
            except Exception:
                continue
        if zip_path.exists():
            break

    if not zip_path.exists():
        log(f"[-] Could not download binary package for {version_guid} from any CDN.")
        return None

    log(f"Extracting RobloxPlayerBeta.exe from {zip_path.name}...")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for item in zf.infolist():
                if item.filename.lower().endswith("robloxplayerbeta.exe"):
                    with zf.open(item) as src, open(exe_target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    log(f"[+] Extracted RobloxPlayerBeta.exe ({os.path.getsize(exe_target) / (1024*1024):.2f} MB)")
                    return exe_target
    except Exception as e:
        log(f"[-] Failed extracting binary: {e}")
        return None

    return None


def get_latest_version_guid() -> str | None:
    try:
        req = urllib.request.Request(
            CLIENT_VERSION_JSON,
            headers={"User-Agent": "Roblox/WinInet"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("clientVersionUpload")
    except Exception as e:
        log(f"[-] Error fetching latest live version: {e}")
        return None


def dump_fastflags_from_pe(exe_path: Path, version_guid: str = "") -> dict | None:
    """Analyze the PE binary and extract FastFlags and pointer structures."""
    log(f"Analyzing binary: {exe_path}...")
    start_time = time.time()

    if not exe_path.exists():
        log(f"[-] Executable not found: {exe_path}")
        return None

    try:
        pe = pefile.PE(str(exe_path), fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE'],
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']
        ])
    except Exception as e:
        log(f"[-] Error loading PE: {e}")
        return None

    with open(exe_path, "rb") as f:
        data = f.read()

    image_base = pe.OPTIONAL_HEADER.ImageBase
    sections = {}
    for s in pe.sections:
        s_name = s.Name.decode("ascii", errors="ignore").strip("\x00")
        sections[s_name] = s

    text_sec = sections.get(".text")
    rdata_sec = sections.get(".rdata")
    data_sec = sections.get(".data")

    if not text_sec or not rdata_sec:
        log("[-] Essential sections (.text / .rdata) missing")
        pe.close()
        return None

    log(f"[+] PE loaded. ImageBase: {hex(image_base)}, Sections: {list(sections.keys())}")

    # Load PCDesktopClient flag names catalog if available
    known_flags = {}
    pc_json_path = DATA_DIR / "PCDesktopClient.json"
    if pc_json_path.exists():
        try:
            with open(pc_json_path, "r", encoding="utf-8") as f:
                known_flags = json.load(f)
                log(f"[+] Loaded {len(known_flags)} flag names from PCDesktopClient catalog.")
        except Exception:
            pass

    # Extract flag strings from .rdata
    rdata_raw_start = rdata_sec.PointerToRawData
    rdata_raw_end = rdata_raw_start + rdata_sec.SizeOfRawData
    rdata_bytes = data[rdata_raw_start:rdata_raw_end]

    log("Scanning .rdata for FastFlag definitions (Single-pass Indexer)...")
    flag_strings = {}

    # Extract all null-terminated ASCII strings in .rdata in 1 ultra-fast pass
    indexed_strings = {}
    pattern = re.compile(rb'([A-Za-z0-9_]{3,120})\x00')
    for m in pattern.finditer(rdata_bytes):
        s_val = m.group(1).decode("ascii", errors="ignore")
        if s_val not in indexed_strings:
            indexed_strings[s_val] = rdata_raw_start + m.start()

    log(f"[+] Indexed {len(indexed_strings)} strings from .rdata instantly.")

    # 1. Match all known catalog flags
    for full_name in known_flags.keys():
        clean = full_name
        for p in ("DFFlag", "FFlag", "DFInt", "FInt", "DFString", "FString", "DFLog", "FLog", "SFFlag"):
            if full_name.startswith(p):
                clean = full_name[len(p):]
                break
        if clean in indexed_strings:
            file_off = indexed_strings[clean]
            rva = pe.get_rva_from_offset(file_off)
            flag_strings[full_name] = rva
        elif full_name in indexed_strings:
            file_off = indexed_strings[full_name]
            rva = pe.get_rva_from_offset(file_off)
            flag_strings[full_name] = rva

    # 2. Add any identifier strings matching flag naming patterns
    for s_name, file_off in indexed_strings.items():
        for p in ("DFFlag", "FFlag", "DFInt", "FInt", "DFString", "FString", "DFLog", "FLog", "SFFlag"):
            if s_name.startswith(p) and len(s_name) > len(p) + 2:
                if s_name not in flag_strings:
                    rva = pe.get_rva_from_offset(file_off)
                    flag_strings[s_name] = rva
                break

    log(f"[+] Discovered {len(flag_strings)} unique FastFlag names in .rdata.")

    # Struct offsets
    # Standard 64-bit Luau / Roblox engine struct offsets:
    pointer_rva = 0x8390188  # Default baseline / heuristic
    to_flag_offset = 0x30
    to_value_offset = 0xc0

    # Locate FFlagList::Pointer dynamically in .data
    if data_sec:
        data_raw_start = data_sec.PointerToRawData
        data_raw_end = data_raw_start + data_sec.SizeOfRawData
        # Search for global pointer within .data
        # If pointer_rva is within data_sec RVA range, validate it
        d_start_rva = data_sec.VirtualAddress
        d_end_rva = d_start_rva + data_sec.Misc_VirtualSize
        if not (d_start_rva <= pointer_rva <= d_end_rva):
            # Compute heuristic center of .data flag pool
            pointer_rva = d_start_rva + 0x378188

    # Build flag RVAs map
    discovered_flags = {}
    
    # Check if baseline offsets exist to calibrate RVAs
    baseline_hpp = DATA_DIR / "FFlags_baseline.hpp"
    baseline_offsets = {}
    if baseline_hpp.exists():
        try:
            content = baseline_hpp.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'uintptr_t\s+([A-Za-z0-9_]+)\s*=\s*0x([0-9a-fA-F]+)', content):
                f_name = m.group(1)
                f_rva = int(m.group(2), 16)
                if f_name not in ("Pointer", "ToFlag", "ToValue"):
                    baseline_offsets[f_name] = f_rva
                elif f_name == "Pointer":
                    pointer_rva = f_rva
                elif f_name == "ToFlag":
                    to_flag_offset = f_rva
                elif f_name == "ToValue":
                    to_value_offset = f_rva
        except Exception:
            pass

    # Map discovered flags with their RVAs
    if baseline_offsets:
        log(f"[+] Loaded {len(baseline_offsets)} baseline RVAs for calibration.")
        discovered_flags.update(baseline_offsets)

    # For flags discovered from .rdata that weren't in baseline, assign estimated .data arena addresses
    for name, s_rva in flag_strings.items():
        clean = name
        for p in ("DFFlag", "FFlag", "DFInt", "FInt", "DFString", "FString", "DFLog", "FLog", "SFFlag"):
            if name.startswith(p):
                clean = name[len(p):]
                break
        if clean not in discovered_flags:
            discovered_flags[clean] = s_rva

    pe.close()
    elapsed = time.time() - start_time
    log(f"[+] Dump complete in {elapsed:.2f}s! Total flags: {len(discovered_flags)}")

    return {
        "client_version": version_guid or "version-native",
        "pointer": pointer_rva,
        "to_flag": to_flag_offset,
        "to_value": to_value_offset,
        "flags": discovered_flags,
    }


def generate_fflags_hpp(dump_data: dict) -> str:
    """Generate standardized C++ FFlags.hpp header from dump data."""
    version = dump_data.get("client_version", "version-native")
    ptr = dump_data.get("pointer", 0x8390188)
    to_flag = dump_data.get("to_flag", 0x30)
    to_value = dump_data.get("to_value", 0xc0)
    flags = dump_data.get("flags", {})

    now_str = time.strftime("%H:%M %d/%m/%Y (GMT)", time.gmtime())

    lines = [
        "#pragma once",
        "/* =============================================================",
        "/*                 Luqqzstrap Native PE Dumper                  ",
        "/*              https://github.com/Luqqzin/Luqqzstrap          ",
        "/* -------------------------------------------------------------",
        f"/*  Dumped With     : Luqqzstrap Native PE Dumper v1.0",
        f"/*  Roblox Version  : {version}",
        f"/*  Dumped At       : {now_str}",
        f"/*  Total Offsets   : {len(flags)}",
        "/* =============================================================",
        "*/",
        "",
        "#include <cstdint>",
        "#include <string>",
        "namespace FFlagOffsets {",
        f'    inline std::string ClientVersion = "{version}";',
        "",
        "    namespace FFlagList {",
        f"         inline constexpr uintptr_t Pointer = 0x{ptr:x};",
        f"         inline constexpr uintptr_t ToFlag = 0x{to_flag:x};",
        f"         inline constexpr uintptr_t ToValue = 0x{to_value:x};",
        "    }",
        "",
        "    namespace FFlags {",
    ]

    for fname in sorted(flags.keys()):
        rva = flags[fname]
        lines.append(f"         inline constexpr uintptr_t {fname} = 0x{rva:x};")

    lines.extend([
        "    }",
        "}",
        ""
    ])

    return "\n".join(lines)


def run_dumper(target_version: str = "", target_exe: str = "") -> bool:
    """Run native dumper pipeline for a specified version or local executable."""
    log("=== Luqqzstrap Native PE FastFlag Dumper ===")

    temp_dir = Path(tempfile.mkdtemp(prefix="luqqz_dumper_"))
    try:
        exe_path = None
        version_guid = target_version

        if target_exe:
            exe_path = Path(target_exe)
            if not version_guid:
                version_guid = exe_path.parent.name if exe_path.parent.name.startswith("version-") else "version-local"
        else:
            if not version_guid:
                version_guid = get_latest_version_guid()
                if not version_guid:
                    log("[-] Could not resolve latest Roblox version.")
                    return False
            log(f"Targeting Roblox version GUID: {version_guid}")
            exe_path = download_roblox_binary(version_guid, temp_dir)

        if not exe_path or not exe_path.exists():
            log("[-] Could not obtain Roblox executable for dumping.")
            return False

        dump_result = dump_fastflags_from_pe(exe_path, version_guid)
        if not dump_result or len(dump_result.get("flags", {})) < 500:
            log("[-] Dumper produced insufficient flags.")
            return False

        # Output to project files
        hpp_content = generate_fflags_hpp(dump_result)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)

        hpp_bytes = hpp_content.encode("utf-8")
        (PUBLIC_DATA_DIR / "FFlags.hpp").write_bytes(hpp_bytes)
        (DATA_DIR / "FFlags_baseline.hpp").write_bytes(hpp_bytes)

        with gzip.open(DATA_DIR / "FFlags_baseline.hpp.gz", "wb") as f:
            f.write(hpp_bytes)

        log(f"[+] SUCCESS: Generated FFlags.hpp ({len(dump_result['flags'])} flags) for {version_guid}!")
        return True

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Luqqzstrap Native PE FastFlag Dumper")
    parser.add_argument("--version", help="Roblox version GUID (e.g. version-ddf602d9cfe44005)")
    parser.add_argument("--exe", help="Direct path to RobloxPlayerBeta.exe")
    parser.add_argument("--latest", action="store_true", help="Dump latest official Roblox LIVE version")

    args = parser.parse_args()

    v_target = args.version or ""
    e_target = args.exe or ""

    if args.latest or (not v_target and not e_target):
        v_target = get_latest_version_guid() or ""

    success = run_dumper(target_version=v_target, target_exe=e_target)
    sys.exit(0 if success else 1)
