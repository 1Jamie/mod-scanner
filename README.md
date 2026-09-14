# mod-scanner

A lightweight Python scanner and Discord bot for detecting copyrighted ROM binaries, console dumps, and direct sprite rips inside `gen1recomp` and decompilation mod releases, with support for distinguishing original hand-drawn demakes.

---

## Overview

Mod releases frequently include third-party textures, music, or scripts. However, distributors must ensure archives do not contain proprietary Nintendo ROMs, decompiled data blobs, or direct asset rips.

Comparing modified assets directly by SHA256 or MD5 fails when dealing with image conversions (for example, raw 2bpp Game Boy tiles converted to 32-bit RGBA PNGs with custom palettes). Standard 8x8 perceptual hashing also produces false positives on simple sprites (like Voltorb vs Electrode) or flags original scratch-drawn demakes that merely share a general silhouette.

`mod-scanner` addresses this through a tiered verification pipeline:

1. **Tier 0: Archive Security (Zip Bomb & Traversal Checks)**
   - Pre-calculates compression ratio per file using zip metadata before decompressing any content.
   - Enforces total uncompressed size and file count limits.
   - Rejects directory traversal (ZipSlip) attempts.

2. **Tier 1: Static Binary & ROM Header Scanner**
   - Inspects the first 4KB chunk of every file stream without loading large files into memory.
   - Matches known console headers and magic bytes across Game Boy, GBC, GBA, N64, GameCube, Wii, Nintendo DS, 3DS, and Nintendo Switch (NSP/XCI).
   - Flags blacklisted binary extensions (`.gba`, `.nds`, `.3ds`, `.z64`, `.nsp`, `.xci`, etc.).

3. **Tier 2: 256-Bit Perceptual Image Hashing (16x16 dHash)**
   - Normalizes alpha channels by compositing RGBA images onto a solid white background before grayscale conversion, preventing transparent pixels from turning black and corrupting luminance calculations.
   - Computes a 16x16 difference hash (256 bits).
   - Compares hashes against reference sprites via bitwise XOR Hamming distance:
     - Distance 0 to 14: Direct rip / minimal recolor (Auto-Reject).
     - Distance 15 to 30: High similarity / potential demake (Flagged for review).
     - Distance > 30: Original custom art (Pass).

4. **Tier 3: Discord Bot Review Workflow**
   - Monitors Discord Forum Channels and Threads for uploaded `.zip` files.
   - For flagged releases, generates a 3-panel side-by-side diff preview image (`[Mod Asset] | [Official Ref] | [Pixel Difference]`).
   - Caps embed fields to avoid hitting Discord character limits and attaches an in-memory `.zip` bundle containing all diff preview PNGs and a text summary report.
   - Provides interactive `[Approve (Whitelist)]` and `[Reject & Delete]` buttons for moderators.

5. **Automated Reference Asset Fetching**
   - On first startup, downloads and indexes sprites directly from public decompilation repositories (such as `pret/pokered`, `pret/pokeyellow`, and `pret/pokefirered`).
   - Caches hashes locally to `.cache/reference_hashes.json`. No copyrighted image assets are committed to this repository.

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt` (Pillow, imagehash, PyYAML, requests, discord.py, pytest)

---

## Installation

```bash
git clone https://github.com/your-username/mod-scanner.git
cd mod-scanner
pip install -r requirements.txt
```

---

## Configuration (`config.yaml`)

Configuration is managed through `config.yaml`. Settings can also be overridden using environment variables.

```yaml
# GitHub token to avoid unauthenticated API/download rate limits (or export GITHUB_TOKEN)
github_token: ""

# Worker process pool limit for CPU-bound hashing and zip parsing
concurrency:
  max_workers: 2

# Upstream decomp repositories to pull canonical reference sprites from on first boot
pret_sources:
  - name: "pokered"
    repo: "pret/pokered"
    branch: "master"
    image_patterns:
      - "gfx/sprites/**/*.png"
      - "gfx/pokemon/**/*.png"
      - "gfx/trainers/**/*.png"
  - name: "pokeyellow"
    repo: "pret/pokeyellow"
    branch: "master"
    image_patterns:
      - "gfx/sprites/**/*.png"
      - "gfx/pokemon/**/*.png"
      - "gfx/trainers/**/*.png"
  - name: "pokefirered"
    repo: "pret/pokefirered"
    branch: "master"
    image_patterns:
      - "graphics/pokemon/**/front.png"
      - "graphics/pokemon/**/back.png"
      - "graphics/trainers/**/*.png"
  - name: "pokeheartgold"
    repo: "pret/pokeheartgold"
    branch: "master"
    image_patterns:
      - "files/graphic/**/*.png"
      - "src/data/graphics/**/*.png"

# Archive safety limits
archive:
  max_unpacked_size_mb: 500
  max_file_count: 50000
  max_compression_ratio: 20.0

# Binary and console ROM rules
binary_rules:
  blacklisted_extensions:
    - ".gb"
    - ".gbc"
    - ".gba"
    - ".nds"
    - ".3ds"
    - ".cia"
    - ".cxi"
    - ".z64"
    - ".n64"
    - ".v64"
    - ".iso"
    - ".wbfs"
    - ".wad"
    - ".nsp"
    - ".xci"
  magic_bytes:
    - name: "Game Boy / GBC Nintendo Logo"
      offset: 0x0104
      hex: "ceed6666cc0d000b03730083000c000d0008111f8889000eaccf"
    - name: "GBA Nintendo Logo Header"
      offset: 0x0004
      hex: "24ffae51699aa2213d84820a84e409ad"
    - name: "GBA Fixed Complement Byte"
      offset: 0x00B2
      hex: "96"
    - name: "N64 ROM (Big Endian)"
      offset: 0x0000
      hex: "80371240"
    - name: "N64 ROM (Byte-swapped)"
      offset: 0x0000
      hex: "37804012"
    - name: "N64 ROM (Little Endian)"
      offset: 0x0000
      hex: "40123780"
    - name: "GameCube / Wii Disc Magic"
      offset: 0x001C
      hex: "c2339f3d"
    - name: "Nintendo DS Logo Header"
      offset: 0x00C0
      hex: "24ffae51699aa2213d84820a84e409ad"
    - name: "Nintendo DS Logo CRC"
      offset: 0x015C
      hex: "cf56"
    - name: "3DS NCCH Partition"
      offset: 0x0100
      hex: "4e434348"
    - name: "3DS NCSD Header"
      offset: 0x0100
      hex: "4e435344"
    - name: "Nintendo Switch NSP (PFS0)"
      offset: 0x0000
      hex: "50465330"
    - name: "Nintendo Switch XCI (HFS0)"
      offset: 0x0000
      hex: "48465330"

# Perceptual image matching
image_rules:
  hash_type: "dhash"
  hash_size: 16
  thresholds:
    auto_reject: 14
    flag_for_review: 30
  generate_diff_preview: true
  preview_panel_size: 64

# Discord bot configuration
discord:
  token: ""                   # Or export DISCORD_BOT_TOKEN
  guild_id: 0
  monitored_channel_ids: []   # Optional list of Forum / Text Channel IDs (empty = all accessible channels)
  mod_review_channel_id: 0    # Channel where flagged embeds and diff bundles are sent
  max_embed_items: 4          # Number of top flagged matches to show in embed
  attach_diff_bundle_zip: true
  auto_delete_violations: false

# Storage paths
paths:
  cache_dir: "./.cache"
  whitelist_file: "./whitelist.json"
```

---

## Developer Workflows & CI/CD Integration

`mod-scanner` provides three ways for mod developers to verify their releases before publishing.

---

### 1. Direct Directory Scanning (CLI)

Mod authors can scan their active project directory or working tree directly without building a `.zip` archive first.

```bash
# Scan current directory
mod-scanner scan .

# Scan a specific mod working directory
mod-scanner scan path/to/mod-source/

# Scan with custom preview output folder
mod-scanner scan path/to/mod-source/ --preview-dir ./my_diffs/

# Exit with code 0 on flagged assets (only fail on hard ROM/rip violations)
mod-scanner scan path/to/mod-source/ --no-fail-on-flagged
```

**CLI Exit Codes:**
- `0`: Clean (passed all checks, or flagged with `--no-fail-on-flagged`).
- `1`: Flagged (potential demakes or edits requiring review).
- `2`: Rejected (prohibited ROM headers, blacklisted binaries, or direct rips detected).

---

### 2. GitHub Actions Integration (`action.yml`)

Include `mod-scanner` in your mod repository CI/CD pipeline to automatically validate pull requests and release builds. The action automatically caches the reference database, posts a Markdown report to GitHub Step Summary, and uploads diff previews as workflow artifacts.

#### Example Workflow (`.github/workflows/scan-mod.yml`):

```yaml
name: Scan Mod Release

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  mod-scan:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Mod Repository
        uses: actions/checkout@v4

      - name: Run Mod Scanner
        uses: 1Jamie/mod-scanner@main
        with:
          path: '.'
          fail-on-flagged: 'true'
          save-previews: 'true'
          upload-artifacts: 'true'
```

#### Action Inputs:
| Input | Description | Default |
| :--- | :--- | :--- |
| `path` | Path to directory or `.zip` file to scan | `.` |
| `config` | Optional path to custom `config.yaml` | `""` |
| `fail-on-flagged` | Fail step if assets are flagged for review (`true`/`false`) | `true` |
| `save-previews` | Generate 3-panel PNG diff previews for flagged assets | `true` |
| `upload-artifacts` | Upload diff previews as a GitHub Actions artifact | `true` |

#### Action Outputs:
| Output | Description |
| :--- | :--- |
| `verdict` | Final scan status (`CLEAN`, `FLAGGED`, or `REJECT`) |
| `scanned-count` | Number of files scanned |
| `violations-count` | Number of hard violations found |
| `flags-count` | Number of flagged assets found |

---

### 3. Discord Self-Service Command (`/check-mod`)

Mod creators can test their releases privately before posting to public forums or release channels:

- **/check-mod [file] [url]**: Runs an ephemeral scan (visible only to the user who ran the command). If assets are flagged, the bot provides direct percentage similarity values and attaches a downloadable `.zip` diff bundle containing all side-by-side sprite comparisons.
- **!check [url]**: Text command alternative for servers or direct messages.
- **!sync**: Synchronizes slash commands across the guild (Admin only).

---

## Discord Bot Server Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create an Application and Bot.
3. Under the **Bot** tab, enable **Message Content Intent**.
4. Invite the bot to your server with permissions to read channels, send messages, attach files, and manage messages.
5. Set your bot token in `config.yaml` or export `DISCORD_BOT_TOKEN`.
6. Set `mod_review_channel_id` to your staff review channel ID.
7. Start the bot:

```bash
python bot.py
```

### How the Bot Handles Automated Uploads
- **Forum Channels / Threads**: When a user creates a new thread in a monitored forum channel or posts a `.zip` in a thread, the bot scans the archive asynchronously without blocking Discord gateway heartbeats.
- **Clean Submissions**: Adds a checkmark reaction (`✅`).
- **Hard Violations (ROM dumps / Blacklisted headers / Rips)**: Adds a cross reaction (`❌`), DMs the author with specific reasons, and optionally removes the post if `auto_delete_violations: true`.
- **Flagged Assets (Demakes / High Similarity)**: Adds a warning reaction (`⚠️`) and posts a review embed to the moderator review channel with:
  - Jump link to the author's thread and message.
  - Top matching sprite diffs.
  - Downloadable `diff_bundle_<modname>.zip` containing all side-by-side diff PNGs and a text breakdown.
  - `[Approve (Whitelist Artwork)]` and `[Reject & Delete]` action buttons.

---

## Testing

Run the automated test suite with pytest:

```bash
python -m pytest -v
```

