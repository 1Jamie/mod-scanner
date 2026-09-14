"""
Command-line interface for mod-scanner.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
from pathlib import Path
import requests

from .config import Config
from .pret_fetcher import load_or_fetch_reference_database
from .scanner import ModScanner, WhitelistManager


def format_status_badge(status: str) -> str:
    if status == "CLEAN":
        return "\033[92m[CLEAN - PASSED]\033[0m"
    elif status == "FLAGGED":
        return "\033[93m[FLAGGED - REVIEW NEEDED]\033[0m"
    elif status == "REJECT":
        return "\033[91m[REJECT - PROHIBITED]\033[0m"
    return f"[{status}]"


def handle_scan(args, config: Config):
    target = args.target
    is_url = target.startswith("http://") or target.startswith("https://")

    print(f"Loading reference database (cache: {config.paths.reference_hashes_file})...")
    scanner = ModScanner(config=config)

    temp_file = None
    try:
        if is_url:
            print(f"Downloading remote archive from: {target}")
            with requests.get(target, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        temp_file.write(chunk)
                temp_file.close()
            scan_path = temp_file.name
        else:
            scan_path = target
            if not os.path.exists(scan_path):
                print(f"\033[91mError: Target file not found: {scan_path}\033[0m", file=sys.stderr)
                sys.exit(1)

        print(f"Scanning archive '{target}'...")
        result = scanner.scan_archive_sync(scan_path)

        print("\n" + "=" * 60)
        print(f" Verdict: {format_status_badge(result.status)}")
        print(f" Summary: {result.summary}")
        print(f" Files Scanned: {result.scanned_file_count} (in {result.elapsed_seconds}s)")
        print("=" * 60)

        if result.violations:
            print("\n\033[91m🚨 VIOLATIONS DETECTED:\033[0m")
            for i, v in enumerate(result.violations, 1):
                print(f"  {i}. [{v.rule_type}] {v.file_path}")
                print(f"     -> {v.message}")

        if result.flags:
            print("\n\033[93m⚠️ FLAGGED ASSETS (POTENTIAL DEMAKES / EDITS):\033[0m")
            out_preview_dir = Path("./scan_previews")
            if args.save_previews:
                out_preview_dir.mkdir(parents=True, exist_ok=True)

            for i, f in enumerate(result.flags, 1):
                print(f"  {i}. {f.file_path}")
                print(f"     Closest Match: {f.matched_ref}")
                print(f"     Hamming Distance: {f.hamming_distance}/256")
                print(f"     Mod Hash: {f.mod_hash}")

                if args.save_previews and f.preview_bytes:
                    clean_name = f.file_path.replace("/", "_").replace("\\", "_")
                    preview_file = out_preview_dir / f"diff_{clean_name}.png"
                    with open(preview_file, "wb") as pf:
                        pf.write(f.preview_bytes)
                    print(f"     Preview Diff Saved: {preview_file}")

        print("")
        if result.is_rejected:
            sys.exit(2)
        elif result.is_flagged:
            sys.exit(1)
        else:
            sys.exit(0)

    finally:
        if temp_file and os.path.exists(temp_file.name):
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass


def handle_update_db(args, config: Config):
    print("Force updating reference database from pret upstream repositories...")
    ref_db = load_or_fetch_reference_database(config, force_refresh=True)
    print(f"\033[92mSuccess! Reference database updated with {len(ref_db.hashes)} asset hashes.\033[0m")


def handle_whitelist(args, config: Config):
    wm = WhitelistManager(config.paths.whitelist_file)
    if args.action == "list":
        print(f"Approved Whitelisted Hashes ({len(wm._approved_hashes)}):")
        for h in sorted(list(wm._approved_hashes)):
            print(f"  - {h}")
    elif args.action == "add":
        if not args.hash:
            print("Error: hash required to add to whitelist", file=sys.stderr)
            sys.exit(1)
        if wm.approve(args.hash):
            print(f"\033[92mHash {args.hash} added to whitelist.\033[0m")
        else:
            print(f"Hash {args.hash} is already in whitelist.")


def main():
    parser = argparse.ArgumentParser(
        prog="mod-scanner",
        description="Copyright and ROM scanner for gen1recomp and decomp mods.",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a local .zip archive or release URL")
    scan_parser.add_argument("target", help="File path or URL to .zip archive")
    scan_parser.add_argument(
        "--save-previews", action="store_true", default=True, help="Save diff preview PNGs to ./scan_previews/"
    )

    # Update DB command
    subparsers.add_parser("update-db", help="Fetch pret sources and refresh reference hash database")

    # Whitelist command
    wl_parser = subparsers.add_parser("whitelist", help="Manage approved asset whitelist")
    wl_parser.add_argument("action", choices=["list", "add"], help="Action to perform")
    wl_parser.add_argument("hash", nargs="?", default="", help="Hash string to add")

    args = parser.parse_args()
    config = Config.from_file(args.config)

    if args.command == "scan":
        handle_scan(args, config)
    elif args.command == "update-db":
        handle_update_db(args, config)
    elif args.command == "whitelist":
        handle_whitelist(args, config)


if __name__ == "__main__":
    main()
