"""Avatar pipeline: install MPFB and MakeHuman packs, build and validate avatars.

Everything in this package runs with the Python standard library. Blender is
started as a subprocess; the scripts it runs live in the repository's
``blender/`` folder.
"""
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[2]
AVATARS_DIR = KIT_ROOT / "avatars"
BLENDER_SCRIPTS = KIT_ROOT / "blender"
STATE_DIR = KIT_ROOT / ".tak"
PROFILE_DIR = STATE_DIR / "blender-user"

MPFB_VERSION = "2.0.17"
MPFB_URL = "https://github.com/makehumancommunity/mpfb2/archive/refs/tags/v2.0.17.zip"
MPFB_SHA256 = "d08e726c798fdc4eefb02b06b6c4efe37d40b5439777e53cf96dce0e5073297d"
# Folder inside the source archive that holds the Blender extension.
MPFB_ARCHIVE_SUBDIR = "mpfb2-2.0.17/src/mpfb/"
# Blender extension repository used for the installed copy.
MPFB_REPO = "user_default"

# Official MakeHuman Community asset packs (CC0). The sha256 values are the
# archives the shipped avatars were built from; a different upstream archive is
# accepted with a warning and its own hash is recorded.
PACKS = {
    "makehuman_system_assets": {
        "file": "makehuman_system_assets_cc0.zip",
        "url": "https://files2.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip",
        "sha256": "b542127a8e25547c7c29c19f2d1d2adb9a664c80396ecd694095dbc8028a0107",
        "page": "https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html",
    },
    "visemes02": {
        "file": "visemes02.zip",
        "url": "https://files2.makehumancommunity.org/functional/visemes02.zip",
        "sha256": "a69ab6fb95ddd5f56f70acc7e859f5f9c6ae613c527d577ea1571eff2183d29e",
        "page": "https://static.makehumancommunity.org/assets/assetpacks/visemes02.html",
    },
    "faceunits01": {
        "file": "faceunits01.zip",
        "url": "https://files2.makehumancommunity.org/functional/faceunits01.zip",
        "sha256": "d113107bd7eb59f3af4df6fc0ec29bfcc593f496d0b336aec14f086a80ce7146",
        "page": "https://static.makehumancommunity.org/assets/assetpacks/faceunits01.html",
    },
}

LICENSE_ID = "CC-BY-4.0"
CREDIT = "talking-avatar-kit by Ghazanfar Ali"
