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
# Default output of ``tak build``; ``--install`` copies a validated build into avatars/<slug>/.
REBUILD_DIR = KIT_ROOT / "build" / "rebuild"

MPFB_VERSION = "2.0.17"
MPFB_URL = "https://github.com/makehumancommunity/mpfb2/archive/refs/tags/v2.0.17.zip"
MPFB_SHA256 = "d08e726c798fdc4eefb02b06b6c4efe37d40b5439777e53cf96dce0e5073297d"
# Folder inside the source archive that holds the Blender extension.
MPFB_ARCHIVE_SUBDIR = "mpfb2-2.0.17/src/mpfb/"
# Blender extension repository used for the installed copy.
MPFB_REPO = "user_default"

# Official MakeHuman Community asset packs. The sha256 values are the archives
# the shipped avatars were built from; a different upstream archive is accepted
# with a warning and its own hash is recorded. ``license`` is the pack's licence
# as its page and its packs/<name>.json state it (every asset in a pack shares
# it; the json also names each asset's author). Assets from a CC-BY pack must be
# credited: the avatar specs carry the credit lines, the manifests list them.
# ``uses`` lists the assets the shipped avatars take from a community pack.
_FILES = "https://files2.makehumancommunity.org"
_PAGES = "https://static.makehumancommunity.org/assets/assetpacks"


def _community(name: str, file: str, sha256: str, license: str, uses: list[str]) -> dict:
    return {"file": file, "url": f"{_FILES}/asset_packs/{name}/{file}", "sha256": sha256,
            "page": f"{_PAGES}/{name}.html", "license": license, "kind": "community", "uses": uses}


PACKS = {
    "makehuman_system_assets": {
        "file": "makehuman_system_assets_cc0.zip",
        "url": f"{_FILES}/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip",
        "sha256": "b542127a8e25547c7c29c19f2d1d2adb9a664c80396ecd694095dbc8028a0107",
        "page": f"{_PAGES}/makehuman_system_assets.html",
        "license": "CC0", "kind": "system", "uses": [],
    },
    "visemes02": {
        "file": "visemes02.zip",
        "url": f"{_FILES}/functional/visemes02.zip",
        "sha256": "a69ab6fb95ddd5f56f70acc7e859f5f9c6ae613c527d577ea1571eff2183d29e",
        "page": f"{_PAGES}/visemes02.html",
        "license": "CC0", "kind": "functional", "uses": [],
    },
    "faceunits01": {
        "file": "faceunits01.zip",
        "url": f"{_FILES}/functional/faceunits01.zip",
        "sha256": "d113107bd7eb59f3af4df6fc0ec29bfcc593f496d0b336aec14f086a80ce7146",
        "page": f"{_PAGES}/faceunits01.html",
        "license": "CC0", "kind": "functional", "uses": [],
    },
    # Natural male skins (Rowan: mindfront_skin_male_african_middleage by Mindfront).
    "skins02": _community("skins02", "skins02_cc0.zip",
                          "1613f1ef3afca53094511d26620ed7cf1d2dedc29ed3d384d60bdebe250698ae", "CC0",
                          ["mindfront_skin_male_african_middleage"]),
    # Rowan's polo shirt (namuhekam) and cargo trousers (Cortu).
    "shirts01": _community("shirts01", "shirts01_cc0.zip",
                           "a5a723b0e84a109bb190fcfeac7f1de4138d875da3e30fe5b3340eac9f38bcd3", "CC0",
                           ["namuhekam_male_polo_shirt"]),
    "pants01": _community("pants01", "pants01_cc0.zip",
                          "e4e0ec60db34f279be291a83cfd7b342a7c5cf09bb7676682a5f39f4f6ac4ad9", "CC0",
                          ["cortu_cargo_pants"]),
    # Mira's double-breasted trouser suit (MargaretToigo).
    "suits01": _community("suits01", "suits01_cc0.zip",
                          "2b1d8676f3863b188e9eea98c1d8f234543d54c440e791d92b819f8ee1861f19", "CC0",
                          ["toigo_female_double-breasted_suit"]),
    # Amina's dress (Mindfront) and hair (punkduck).
    "dress03": _community("dress03", "dress03_cc-by.zip",
                          "d35487edda8347ac8d0250207007c18056d7aaac404e91946bf9cf1399f2bcd8", "CC-BY",
                          ["mindfront_f_dress_09"]),
    "hair03": _community("hair03", "hair03_ccby.zip",
                         "776c277cb6bcebc32907e05fa94d119e48742cdc1c34183996fc3e65e17a2740", "CC-BY",
                         ["punkduck_alpha7_curly"]),
    # Elena's hair (Elvaerwyn), sweater (Mindfront) and skirt (punkduck).
    "hair02": _community("hair02", "hair02_ccby.zip",
                         "c681e5efd37df4007a52253a8d071aedbfe3b614f199d8dae4ae76d5bd7d95c9", "CC-BY",
                         ["elvs_50s_updo"]),
    "shirts02": _community("shirts02", "shirts02_ccby.zip",
                           "d711ca9f73212de855257ac08422e1e0ccb802e5231315c2a360d0fcfea5033e", "CC-BY",
                           ["mindfront_lusekofta"]),
    "skirts02": _community("skirts02", "skirts02_cc-by.zip",
                           "20958a4669d88efc8295e2a4f5c97677f97ca47607478ee99e1a141525cff5b3", "CC-BY",
                           ["punkduck_skirt_native_american_fashion"]),
}

LICENSE_ID = "CC-BY-4.0"
CREDIT = "talking-avatar-kit by Ghazanfar Ali"
