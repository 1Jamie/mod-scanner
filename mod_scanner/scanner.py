"""
Core orchestrator for scanning mod archives across all tiers.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Set
from PIL import Image

from .config import Config
from .core.archive import open_safe_zip, ArchiveSecurityError
from .core.binary_scanner import check_file_stream_for_magic, BinaryViolation
from .core.image_scanner import (
    compute_image_hash,
    calculate_hamming_distance,
    generate_diff_preview,
    ImageMatchResult,
)
from .pret_fetcher import ReferenceDatabase, load_or_fetch_reference_database

logger = logging.getLogger("mod_scanner.scanner")


@dataclass
class ScanViolation:
    file_path: str
    rule_type: str
    message: str


@dataclass
class ScanFlag:
    file_path: str
    matched_ref: str
    hamming_distance: int
    mod_hash: str
    ref_hash: str
    preview_bytes: Optional[bytes] = None


@dataclass
class ScanResult:
    status: str  # "CLEAN", "FLAGGED", "REJECT"
    summary: str
    scanned_file_count: int
    elapsed_seconds: float
    violations: List[ScanViolation] = field(default_factory=list)
    flags: List[ScanFlag] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.status == "CLEAN"

    @property
    def is_rejected(self) -> bool:
        return self.status == "REJECT"

    @property
    def is_flagged(self) -> bool:
        return self.status == "FLAGGED"


class WhitelistManager:
    """Manages moderator-approved asset hashes stored in a flat JSON file."""
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._approved_hashes: Set[str] = set()
        self.load()

    def load(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._approved_hashes = set(data.get("approved_hashes", []))
            except Exception as e:
                logger.warning(f"Could not load whitelist {self.file_path}: {e}")
                self._approved_hashes = set()

    def is_approved(self, image_hash: str) -> bool:
        return image_hash in self._approved_hashes

    def approve(self, image_hash: str, note: str = "") -> bool:
        if image_hash in self._approved_hashes:
            return False
        self._approved_hashes.add(image_hash)
        self._save()
        return True

    def _save(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump({
                "approved_hashes": sorted(list(self._approved_hashes))
            }, f, indent=2)


class ModScanner:
    """
    Main scanner instance holding configuration and reference bank.
    """
    def __init__(self, config: Optional[Config] = None, ref_db: Optional[ReferenceDatabase] = None):
        self.config = config or Config.from_file()
        self.ref_db = ref_db or load_or_fetch_reference_database(self.config)
        self.whitelist = WhitelistManager(self.config.paths.whitelist_file)
        self._pool: Optional[ProcessPoolExecutor] = None

    def get_executor(self) -> ProcessPoolExecutor:
        if self._pool is None:
            max_workers = max(1, self.config.concurrency.max_workers)
            self._pool = ProcessPoolExecutor(max_workers=max_workers)
        return self._pool

    def close(self):
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None

    def scan_archive_sync(self, zip_source: str | os.PathLike | bytes | BinaryIO) -> ScanResult:
        """
        Synchronously scans a zip archive through Tier 0 (Safety), Tier 1 (Binary/ROM),
        and Tier 2 (Perceptual Image Hashing).
        """
        start_time = time.time()
        violations: List[ScanViolation] = []
        flags: List[ScanFlag] = []

        # 1. Tier 0: Open safe zip archive (enforces compression ratio, size, path traversal)
        try:
            z = open_safe_zip(zip_source, self.config.archive)
        except ArchiveSecurityError as e:
            return ScanResult(
                status="REJECT",
                summary=f"Archive security check failed: {e}",
                scanned_file_count=0,
                elapsed_seconds=round(time.time() - start_time, 3),
                violations=[ScanViolation(file_path="archive", rule_type="ArchiveSecurity", message=str(e))],
            )

        scanned_files = 0

        # Iterate over zip members without extracting to disk
        try:
            for zinfo in z.infolist():
                if zinfo.is_dir() or zinfo.filename.endswith("/"):
                    continue

                filename = zinfo.filename
                scanned_files += 1

                # 2. Tier 1: Binary & Magic Byte Scan (Streamed chunk)
                with z.open(zinfo, "r") as file_stream:
                    binary_violation = check_file_stream_for_magic(
                        stream=file_stream,
                        filename=filename,
                        rules=self.config.binary_rules,
                    )
                    if binary_violation:
                        violations.append(
                            ScanViolation(
                                file_path=filename,
                                rule_type="ConsoleROMHeader",
                                message=binary_violation.reason,
                            )
                        )
                        # Hard binary violations immediately classify as REJECT
                        continue

                # 3. Tier 2: Perceptual Image Hashing (PNG, BMP, JPG)
                if filename.lower().endswith((".png", ".bmp", ".jpg", ".jpeg")):
                    try:
                        with z.open(zinfo, "r") as img_stream:
                            raw_data = img_stream.read()
                            img = Image.open(io.BytesIO(raw_data))
                            img.load()

                            mod_hash = compute_image_hash(
                                img,
                                hash_size=self.config.image_rules.hash_size,
                                hash_type=self.config.image_rules.hash_type,
                            )

                            # Skip if this asset has been whitelisted by a moderator
                            if self.whitelist.is_approved(mod_hash):
                                continue

                            # Find closest matching reference asset
                            best_match_key = None
                            best_distance = 999999
                            best_ref_hash = None

                            for ref_key, ref_hash in self.ref_db.hashes.items():
                                dist = calculate_hamming_distance(mod_hash, ref_hash)
                                if dist < best_distance:
                                    best_distance = dist
                                    best_match_key = ref_key
                                    best_ref_hash = ref_hash
                                    if dist == 0:
                                        break

                            # Evaluate thresholds
                            if best_match_key and best_distance <= self.config.image_rules.threshold_auto_reject:
                                violations.append(
                                    ScanViolation(
                                        file_path=filename,
                                        rule_type="DirectAssetRip",
                                        message=f"Image matches canonical asset '{best_match_key}' (Hamming Distance: {best_distance}/{self.config.image_rules.hash_size ** 2})",
                                    )
                                )
                            elif best_match_key and best_distance <= self.config.image_rules.threshold_flag_for_review:
                                # Generate 3-panel diff preview
                                preview_bytes = None
                                if self.config.image_rules.generate_diff_preview:
                                    ref_img = self.ref_db.get_reference_image(best_match_key)
                                    if ref_img:
                                        preview_canvas = generate_diff_preview(
                                            mod_img=img,
                                            ref_img=ref_img,
                                            panel_size=self.config.image_rules.preview_panel_size,
                                        )
                                        buf = io.BytesIO()
                                        preview_canvas.save(buf, format="PNG")
                                        preview_bytes = buf.getvalue()

                                flags.append(
                                    ScanFlag(
                                        file_path=filename,
                                        matched_ref=best_match_key,
                                        hamming_distance=best_distance,
                                        mod_hash=mod_hash,
                                        ref_hash=best_ref_hash or "",
                                        preview_bytes=preview_bytes,
                                    )
                                )
                    except Exception as e:
                        logger.debug(f"Could not parse image {filename}: {e}")
        finally:
            z.close()

        elapsed = round(time.time() - start_time, 3)

        if violations:
            return ScanResult(
                status="REJECT",
                summary=f"Found {len(violations)} prohibited asset/ROM violation(s)",
                scanned_file_count=scanned_files,
                elapsed_seconds=elapsed,
                violations=violations,
                flags=flags,
            )
        elif flags:
            return ScanResult(
                status="FLAGGED",
                summary=f"Found {len(flags)} asset(s) with high similarity needing moderator review",
                scanned_file_count=scanned_files,
                elapsed_seconds=elapsed,
                violations=violations,
                flags=flags,
            )
        else:
            return ScanResult(
                status="CLEAN",
                summary=f"Scan complete: {scanned_files} files checked, no violations found.",
                scanned_file_count=scanned_files,
                elapsed_seconds=elapsed,
                violations=[],
                flags=[],
            )
