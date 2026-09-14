"""
Binary scanner for detecting console ROM headers and blacklisted extensions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import BinaryIO, Optional
from ..config import BinaryRules, MagicByteRule


@dataclass
class BinaryViolation:
    filename: str
    rule_name: str
    reason: str


def check_file_stream_for_magic(
    stream: BinaryIO,
    filename: str,
    rules: BinaryRules,
    chunk_size: int = 4096,
) -> Optional[BinaryViolation]:
    """
    Scans the beginning header chunk (default 4KB) of a stream for known console magic bytes
    and verifies filename extensions against blacklists.
    Does NOT load entire files into memory.
    """
    # 1. Check extension blacklist
    _, ext = os.path.splitext(filename)
    ext_lower = ext.lower()
    if ext_lower in rules.blacklisted_extensions:
        return BinaryViolation(
            filename=filename,
            rule_name="Blacklisted Extension",
            reason=f"File '{filename}' has a prohibited console ROM/container extension '{ext_lower}'",
        )

    # 2. Read only the first chunk for header verification
    header_chunk = stream.read(chunk_size)
    if not header_chunk:
        return None

    header_len = len(header_chunk)
    for rule in rules.magic_bytes:
        req_len = rule.offset + len(rule.raw_bytes)
        if header_len >= req_len:
            extracted = header_chunk[rule.offset : req_len]
            if extracted == rule.raw_bytes:
                return BinaryViolation(
                    filename=filename,
                    rule_name=rule.name,
                    reason=f"File '{filename}' matches console ROM header signature '{rule.name}' at offset 0x{rule.offset:04X}",
                )

    return None
