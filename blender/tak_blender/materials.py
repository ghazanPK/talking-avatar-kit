"""glTF-friendly materials for the avatar parts.

Every material is a single Principled BSDF whose inputs map onto glTF 2.0 and
the KHR_materials_* extensions three.js supports (specular, ior, clearcoat,
sheen), plus KHR_texture_transform for the tiled skin detail normal map.
"""
import bpy
import numpy as np

from . import textures


def _image_of(obj):
    """The diffuse image MPFB attached to the object's material (or None)."""
    mat = obj.active_material
    if not mat or not mat.use_nodes:
        return None
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image and "normal" not in node.image.name.lower() \
                and not node.image.name.lower().endswith("_ao.png"):
            return node.image
    return None


def _image_named(obj, needle):
    mat = obj.active_material
    if not mat or not mat.use_nodes:
        return None
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image and needle in node.image.name.lower():
            return node.image
    return None


def _new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for node in list(nodes):
        if node.type != "OUTPUT_MATERIAL":
            nodes.remove(node)
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (200, 0)
    mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Metallic"].default_value = 0.0
    return mat, bsdf


def _tex(mat, image, location, non_color=False):
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.location = location
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return node


def _assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for slot in obj.material_slots:
        slot.link = "DATA"
        slot.material = mat


def _base_color(mat, bsdf, image, vertex_color=False):
    tex = _tex(mat, image, (-500, 200))
    links = mat.node_tree.links
    if vertex_color:
        attr = mat.node_tree.nodes.new("ShaderNodeVertexColor")
        attr.layer_name = "Color"
        attr.location = (-500, 450)
        mix = mat.node_tree.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (-150, 300)
        mix.inputs["Factor"].default_value = 1.0
        links.new(tex.outputs["Color"], mix.inputs["A"])
        links.new(attr.outputs["Color"], mix.inputs["B"])
        links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    else:
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return tex


def _normal_map(mat, bsdf, image, strength, tiling=None, socket="Normal"):
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    tex = _tex(mat, image, (-500, -300), non_color=True)
    if tiling:
        coord = nodes.new("ShaderNodeTexCoord")
        coord.location = (-1000, -300)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-800, -300)
        mapping.inputs["Scale"].default_value = (tiling, tiling, 1.0)
        links.new(coord.outputs["UV"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    nmap = nodes.new("ShaderNodeNormalMap")
    nmap.location = (-150, -300)
    nmap.inputs["Strength"].default_value = strength
    links.new(tex.outputs["Color"], nmap.inputs["Color"])
    links.new(nmap.outputs["Normal"], bsdf.inputs[socket])
    return tex


def _alpha(mat, bsdf, tex):
    mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"


def _specular(bsdf, level, ior=1.45):
    bsdf.inputs["IOR"].default_value = ior
    bsdf.inputs["Specular IOR Level"].default_value = level


def skin(obj, slug, cfg, limits, work):
    image = textures.limit_size(textures.own_copy(_image_of(obj), f"{slug}_skin"), limits["skin_max"])
    if "tint" in cfg:
        textures.scale_rgb(image, cfg["tint"][:3])
    textures.set_alpha(image, 1.0)
    image.pack()
    mat, bsdf = _new_material("skin")
    _base_color(mat, bsdf, image)
    bsdf.inputs["Roughness"].default_value = cfg.get("roughness", 0.58)
    _specular(bsdf, cfg.get("specular", 0.36), 1.4)
    detail = work.get("skin_detail")
    if detail is None:
        detail = work["skin_detail"] = textures.make_skin_detail_normal("skin_detail_normal")
    _normal_map(mat, bsdf, detail, cfg.get("detail_normal_strength", 0.3), tiling=48.0)
    # Faint sheen for the soft rim of fine facial hair (KHR_materials_sheen).
    bsdf.inputs["Sheen Weight"].default_value = 1.0
    bsdf.inputs["Sheen Roughness"].default_value = 0.55
    bsdf.inputs["Sheen Tint"].default_value = (0.03, 0.025, 0.022, 1.0)
    _assign(obj, mat)
    return mat


def eyes(obj, slug, mpfb, cfg, limits):
    source = bpy.data.images.load(str(mpfb.eye_material(cfg["material"]).with_name(
        _eye_texture_name(mpfb.eye_material(cfg["material"])))), check_existing=True)
    image = textures.limit_size(textures.own_copy(source, f"{slug}_eyes"), limits["eyes_max"])
    textures.tune_eye(image)
    image.pack()
    mat, bsdf = _new_material("eyes")
    _base_color(mat, bsdf, image)
    bsdf.inputs["Roughness"].default_value = 0.35
    _specular(bsdf, 0.5, 1.376)
    # Wet cornea: a smooth clearcoat layer gives the catch-light (KHR_materials_clearcoat).
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.03
    bsdf.inputs["Coat IOR"].default_value = 1.376
    _assign(obj, mat)
    return mat


def _eye_texture_name(mhmat_path):
    for line in mhmat_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "diffuseTexture":
            return parts[1]
    raise LookupError(f"{mhmat_path.name} has no diffuseTexture")


def card(obj, slug, role, limits, darken=1.0, roughness=0.6, specular=0.3):
    """Alpha-textured cards: eyebrows and eyelashes."""
    image = textures.limit_size(textures.own_copy(_image_of(obj), f"{slug}_{role}"), limits["default_max"])
    if darken != 1.0:
        textures.scale_rgb(image, darken)
    textures.bleed_alpha(image)
    image.pack()
    mat, bsdf = _new_material(role)
    tex = _base_color(mat, bsdf, image)
    _alpha(mat, bsdf, tex)
    bsdf.inputs["Roughness"].default_value = roughness
    _specular(bsdf, specular)
    _assign(obj, mat)
    return mat


def hair(obj, slug, cfg, limits):
    image = textures.limit_size(textures.own_copy(_image_of(obj), f"{slug}_hair"), limits["default_max"])
    if "base_color" in cfg:
        textures.scale_rgb(image, cfg["base_color"][:3])
    textures.bleed_alpha(image)
    image.pack()
    mat, bsdf = _new_material("hair")
    tex = _base_color(mat, bsdf, image)
    _alpha(mat, bsdf, tex)
    bsdf.inputs["Roughness"].default_value = cfg.get("roughness", 0.6)
    _specular(bsdf, 0.35, 1.55)
    bsdf.inputs["Sheen Weight"].default_value = 1.0
    bsdf.inputs["Sheen Roughness"].default_value = 0.4
    bsdf.inputs["Sheen Tint"].default_value = (0.05, 0.045, 0.04, 1.0)
    _assign(obj, mat)
    return mat


def mouth_part(obj, slug, role, limits, brightness, roughness, specular):
    """Teeth and tongue: dimmer albedo and a vertex-colour occlusion toward the throat."""
    image = textures.limit_size(textures.own_copy(_image_of(obj), f"{slug}_{role}"), limits["default_max"])
    textures.scale_rgb(image, brightness)
    textures.set_alpha(image, 1.0)
    image.pack()
    mat, bsdf = _new_material(role)
    _base_color(mat, bsdf, image, vertex_color=True)
    bsdf.inputs["Roughness"].default_value = roughness
    _specular(bsdf, specular)
    _assign(obj, mat)
    return mat


def mouth_occlusion(obj, front_level=1.0, back_level=0.22, power=1.4):
    """Bake a front-to-back darkening into a 'Color' attribute (glTF COLOR_0).

    Teeth and tongue are lit as if they were outside the mouth in a real-time
    renderer; darkening them toward the throat stops them glowing.
    """
    mesh = obj.data
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    world = np.array(obj.matrix_world)
    co_w = co @ world[:3, :3].T + world[:3, 3]
    depth = co_w[:, 1]  # Blender -Y is the character's front
    t = (depth - depth.min()) / max(depth.max() - depth.min(), 1e-6)
    level = front_level + (back_level - front_level) * np.clip(t, 0, 1) ** power
    attr = mesh.color_attributes.get("Color") or mesh.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
    rgba = np.repeat(level[:, None], 4, axis=1).astype(np.float32)
    rgba[:, 3] = 1.0
    attr.data.foreach_set("color", rgba.ravel())
    mesh.color_attributes.active_color = attr
    mesh.color_attributes.render_color_index = mesh.color_attributes.find("Color")


def clothing(obj, slug, cfg, limits):
    slot = cfg["slot"]
    mat, bsdf = _new_material(slot)
    image = _image_of(obj)
    if cfg.get("keep_texture", True) and image is not None:
        image = textures.limit_size(textures.own_copy(image, f"{slug}_{slot}"), limits["default_max"])
        if "base_color" in cfg:
            textures.scale_rgb(image, cfg["base_color"][:3])
        textures.set_alpha(image, 1.0)
        image.pack()
        _base_color(mat, bsdf, image)
    else:
        color = list(cfg.get("base_color", (0.5, 0.5, 0.5)))[:3] + [1.0]
        bsdf.inputs["Base Color"].default_value = color
        mat.diffuse_color = color
    normal = _image_named(obj, "normal")
    if normal is not None:
        normal = textures.limit_size(textures.own_copy(normal, f"{slug}_{slot}_normal"), limits["default_max"])
        normal.pack()
        _normal_map(mat, bsdf, normal, 1.0)
    bsdf.inputs["Roughness"].default_value = cfg.get("roughness", 0.7)
    _specular(bsdf, 0.3)
    _assign(obj, mat)
    return mat
