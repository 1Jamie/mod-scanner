import io
import pytest
from mod_scanner.config import Config
from mod_scanner.core.binary_scanner import check_file_stream_for_magic


@pytest.fixture
def binary_rules():
    config = Config.from_file("config.yaml")
    return config.binary_rules


def test_blacklisted_extension_detected(binary_rules):
    stream = io.BytesIO(b"dummy")
    violation = check_file_stream_for_magic(stream, "roms/pokemon_fire.gba", binary_rules)
    assert violation is not None
    assert "prohibited console ROM/container extension" in violation.reason


def test_gb_nintendo_logo_detected(binary_rules):
    # GB Nintendo logo at 0x0104
    header = bytearray(512)
    logo_bytes = bytes.fromhex("ceed6666cc0d000b03730083000c000d0008111f8889000eaccf")
    header[0x0104 : 0x0104 + len(logo_bytes)] = logo_bytes

    stream = io.BytesIO(header)
    violation = check_file_stream_for_magic(stream, "renamed_data.bin", binary_rules)
    assert violation is not None
    assert "Game Boy" in violation.rule_name


def test_gba_logo_header_detected(binary_rules):
    # GBA Nintendo logo header at 0x0004
    header = bytearray(512)
    gba_logo = bytes.fromhex("24ffae51699aa2213d84820a84e409ad")
    header[0x0004 : 0x0004 + len(gba_logo)] = gba_logo

    stream = io.BytesIO(header)
    violation = check_file_stream_for_magic(stream, "asset.dat", binary_rules)
    assert violation is not None
    assert "GBA" in violation.rule_name


def test_contained_signature_detected(binary_rules):
    # Embedded 3DS bcres package in custom binary file
    payload = b"RPII1\x00\x00\x00\x98\x00\x00\x000\x00\x00\x00AABO.bcres.cx\x00\x00"
    stream = io.BytesIO(payload)
    violation = check_file_stream_for_magic(stream, "assets/rumble_pii.pack", binary_rules)
    assert violation is not None
    assert "bcres" in violation.rule_name


def test_n64_magic_detected(binary_rules):
    # N64 big endian magic 0x80371240 at 0x0000
    header = bytearray(512)
    header[0:4] = bytes.fromhex("80371240")

    stream = io.BytesIO(header)
    violation = check_file_stream_for_magic(stream, "custom_level.bin", binary_rules)
    assert violation is not None
    assert "N64" in violation.rule_name


def test_switch_nsp_magic_detected(binary_rules):
    # Switch PFS0 at 0x0000
    header = bytearray(512)
    header[0:4] = b"PFS0"

    stream = io.BytesIO(header)
    violation = check_file_stream_for_magic(stream, "update.pkg", binary_rules)
    assert violation is not None
    assert "Nintendo Switch" in violation.rule_name


def test_clean_file_passes(binary_rules):
    stream = io.BytesIO(b"This is completely clean text or JSON configuration data.")
    violation = check_file_stream_for_magic(stream, "config.json", binary_rules)
    assert violation is None
