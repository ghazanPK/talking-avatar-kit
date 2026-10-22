"""glTF export and GLB post-processing."""
import json
import struct

import bpy

# Material name -> (alphaMode, alphaCutoff, doubleSided)
ALPHA = {
    "eyebrows": ("BLEND", None, False),
    "eyelashes": ("BLEND", None, True),
    "hair": ("MASK", 0.4, True),
    # Garments are open at cuffs and collars; their insides must stay visible.
    "outfit": ("OPAQUE", None, True),
    "top": ("OPAQUE", None, True),
    "bottom": ("OPAQUE", None, True),
    "shoes": ("OPAQUE", None, True),
    "hat": ("OPAQUE", None, True),
    "accessory": ("OPAQUE", None, True),
}
EYE_MARK = "tak_eye_treatment"
EYE_TREATMENT = "brown iris, calmed sclera, clearcoat, roughness 0.35"


def export_glb(path, objects, active, jpeg_quality=90):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    kwargs = dict(
        filepath=str(path), export_format="GLB", use_selection=True, export_apply=False,
        export_skins=True, export_morph=True, export_morph_normal=False,
        export_morph_tangent=False, export_materials="EXPORT", export_image_format="JPEG",
        export_jpeg_quality=jpeg_quality, export_texcoords=True, export_normals=True,
        export_tangents=False, export_animations=False, export_yup=True,
        export_influence_nb=4, export_all_influences=False, export_vertex_color="MATERIAL",
        export_try_sparse_sk=True, export_extras=False, export_cameras=False, export_lights=False,
    )
    props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    bpy.ops.export_scene.gltf(**{k: v for k, v in kwargs.items() if k in props})


def read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or length != len(data):
        raise ValueError(f"{path.name} is not a valid GLB")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("first GLB chunk is not JSON")
    gltf = json.loads(data[20:20 + json_length])
    return gltf, data[20 + json_length:]


def write_glb(path, gltf, rest):
    body = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body += b" " * ((-len(body)) % 4)
    total = 12 + 8 + len(body) + len(rest)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(body), 0x4E4F534A)
                     + body + rest)


def postprocess(path, asset_extras, copyright=None):
    """Fix alpha modes and sidedness per material and stamp asset metadata."""
    gltf, rest = read_glb(path)
    for material in gltf.get("materials", []):
        # Blender appends ".001" when a role name was taken; the GLB uses the role.
        name = material.get("name", "").split(".")[0]
        material["name"] = name
        if name == "eyes":
            # Marks the eye look (textures.tune_eye + clearcoat) so tak.pipeline.glb_eyes
            # never applies it a second time.
            material.setdefault("extras", {})[EYE_MARK] = EYE_TREATMENT
        mode, cutoff, double = ALPHA.get(name, ("OPAQUE", None, False))
        material["alphaMode"] = mode
        material.pop("alphaCutoff", None)
        if cutoff is not None:
            material["alphaCutoff"] = cutoff
        if double:
            material["doubleSided"] = True
        else:
            material.pop("doubleSided", None)
    for mesh in gltf.get("meshes", []):
        # Every morph target starts at zero (a neutral face) in any viewer.
        if "weights" in mesh:
            mesh["weights"] = [0.0] * len(mesh["weights"])
    asset = gltf.setdefault("asset", {})
    asset.setdefault("extras", {}).update(asset_extras)
    if copyright:
        asset["copyright"] = copyright
    write_glb(path, gltf, rest)
    return gltf
