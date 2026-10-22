"""FBX export helpers: Unity-friendly settings, material rebuild, Unity-space skeleton.

Coordinate conventions
----------------------
Blender is right-handed, +Z up, and the avatars face -Y. The FBX is written
Y-up with -Z forward, so it is right-handed, +Y up, the character facing +Z.
The exporter puts that axis change on the root object as a -90 degree X
rotation, and its "Apply Transform" option does not bake it into armatures.
``y_up_data`` therefore rotates the armature and mesh data by -90 degrees
about X and gives the armature object the opposite +90 degree rotation: the
character looks the same in Blender, and in the FBX the two rotations cancel,
so Unity gets an identity root with bones and meshes already Y-up.

Unity converts FBX to its left-handed space by negating X, so a Blender
point (x, y, z) arrives in Unity at (-x, z, -y) metres (the map C below) and
a Blender world rotation R arrives as C R S with S = diag(-1, 1, 1): each
bone keeps its Blender axes, its local +Y still runs along the bone.
"""
import math

import bpy
from mathutils import Matrix, Vector

# Blender (x, y, z) -> Unity (-x, z, -y)
TO_UNITY = Matrix(((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)))
FLIP_X = Matrix(((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
Y_UP = Matrix.Rotation(math.radians(-90.0), 4, "X")

FBX_SETTINGS = dict(
    use_selection=False,
    object_types={"ARMATURE", "MESH"},
    global_scale=1.0,
    apply_unit_scale=True,
    apply_scale_options="FBX_SCALE_ALL",  # FBX unit cm, data x100: Unity "Convert Units" gives 1 unit = 1 m, scale 1
    axis_forward="-Z",
    axis_up="Y",
    use_space_transform=True,
    bake_space_transform=False,  # broken for armatures; y_up_data() cancels the root rotation instead
    use_mesh_modifiers=False,  # keep shape keys; the armature modifier is the only modifier
    mesh_smooth_type="OFF",  # write split normals, no smoothing groups
    use_tspace=True,
    use_triangles=False,
    use_custom_props=False,
    add_leaf_bones=False,
    primary_bone_axis="Y",
    secondary_bone_axis="X",
    use_armature_deform_only=False,
    armature_nodetype="NULL",
    bake_anim=False,
    path_mode="RELATIVE",
    embed_textures=False,
    colors_type="SRGB",
    use_metadata=True,
)


def relative_texture_paths_only():
    """Make the FBX exporter write texture FileName fields relative as well.

    The exporter stores an absolute ``FileName`` next to ``RelativeFilename``;
    that would put the exporting machine's folders into a file meant for
    redistribution. Readers (Unity, Blender, Autodesk) resolve the relative
    path against the FBX folder.
    """
    from io_scene_fbx import export_fbx_bin

    original = getattr(export_fbx_bin._gen_vid_path, "_tak_original", export_fbx_bin._gen_vid_path)

    def gen_vid_path(img, scene_data):
        _abs, rel = original(img, scene_data)
        rel = rel.replace("\\", "/")
        return rel, rel

    gen_vid_path._tak_original = original
    export_fbx_bin._gen_vid_path = gen_vid_path


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures, bpy.data.images):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


def find_rig():
    rigs = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if len(rigs) != 1:
        raise RuntimeError(f"expected one armature, found {len(rigs)}")
    rig = rigs[0]
    # Skinned meshes only: the glTF importer also adds an unparented bone-display shape.
    meshes = sorted((o for o in bpy.data.objects if o.type == "MESH" and o.parent == rig), key=lambda o: o.name)
    return rig, meshes


def remove_extras(rig, meshes):
    """Delete everything except the rig and its meshes (bone shapes, cameras, lights)."""
    keep = {rig.name, *(m.name for m in meshes)}
    for pbone in rig.pose.bones:
        pbone.custom_shape = None
    for obj in list(bpy.data.objects):
        if obj.name not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)


# ---------------------------------------------------------------- materials

def _image(path, non_color):
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def rebuild_material(mat, plan, textures_dir):
    """Replace the glTF importer's node tree with a plain Principled BSDF the FBX exporter maps.

    Base colour (and alpha) -> FBX DiffuseColor / TransparencyFactor, normal map -> NormalMap,
    roughness and metallic as values (glTF packs them in one texture the FBX material
    model has no slot for; the Unity metallic-smoothness map is written separately).
    """
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    factor = plan.get("base_color_factor") or [1.0, 1.0, 1.0, 1.0]
    bsdf.inputs["Base Color"].default_value = (factor[0], factor[1], factor[2], 1.0)
    bsdf.inputs["Alpha"].default_value = factor[3]
    bsdf.inputs["Metallic"].default_value = plan.get("metallic", 0.0)
    bsdf.inputs["Roughness"].default_value = plan.get("roughness", 0.5)
    alpha_mode = plan.get("alpha_mode", "OPAQUE")
    base = plan.get("base_color")
    if base:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.location = (-400, 200)
        tex.image = _image(textures_dir / base["file"], False)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if alpha_mode != "OPAQUE":
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    normal = plan.get("normal")
    if normal:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.location = (-600, -300)
        tex.image = _image(textures_dir / normal["file"], True)
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-250, -300)
        nmap.inputs["Strength"].default_value = normal.get("scale", 1.0)
        nt.links.new(tex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    mat.use_backface_culling = not plan.get("double_sided", False)
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED" if alpha_mode == "BLEND" else "DITHERED"
    if alpha_mode == "MASK" and hasattr(mat, "alpha_threshold"):
        mat.alpha_threshold = plan.get("alpha_cutoff", 0.5)


def write_unity_map(src, dst, metallic, roughness, specular_f0=None):
    """glTF metallic-roughness texture (G roughness, B metallic) -> a Unity map with smoothness in A.

    Metallic workflow: RGB = metallic. Specular workflow (``specular_f0`` given, for
    dielectrics with KHR_materials_specular/ior): RGB = F0 reflectance, sRGB-encoded
    because Unity imports specular maps as colour textures.
    """
    import numpy as np

    img = _image(src, True)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    out = np.zeros_like(px)
    if specular_f0 is None:
        out[:, 0] = np.clip(px[:, 2] * metallic, 0.0, 1.0)
    else:
        f0 = float(specular_f0)
        out[:, 0] = 12.92 * f0 if f0 <= 0.0031308 else 1.055 * f0 ** (1 / 2.4) - 0.055
    out[:, 1] = out[:, 0]
    out[:, 2] = out[:, 0]
    out[:, 3] = np.clip(1.0 - px[:, 1] * roughness, 0.0, 1.0)
    new = bpy.data.images.new(dst.stem, w, h, alpha=True, float_buffer=False, is_data=True)
    new.alpha_mode = "STRAIGHT"
    new.pixels.foreach_set(out.ravel())
    new.filepath_raw = str(dst)
    new.file_format = "PNG"
    new.save()
    bpy.data.images.remove(new)
    return {"width": w, "height": h}


# ---------------------------------------------------------------- Unity-space data

def y_up_data(rig, meshes):
    """Rotate armature and mesh data to Y-up and counter-rotate the armature object (see module doc)."""
    for obj in meshes:
        if obj.parent != rig or any(abs(a - b) > 1e-5 for ra, rb in zip(obj.matrix_local, Matrix.Identity(4))
                                    for a, b in zip(ra, rb)):
            raise RuntimeError(f"mesh {obj.name} is not at the armature origin; cannot convert to Y-up")
    world = rig.matrix_world.copy()
    rig.data.transform(Y_UP)
    for obj in meshes:
        obj.data.transform(Y_UP, shape_keys=True)
        obj.data.update()
    rig.matrix_world = world @ Y_UP.inverted()
    bpy.context.view_layer.update()


def _unity_rotation(mat3):
    """Blender world rotation -> Unity world rotation."""
    return TO_UNITY @ mat3 @ FLIP_X


def _quat_xyzw(mat3):
    q = mat3.to_quaternion().normalized()
    if q.w < 0:
        q.negate()
    return [round(q.x, 7), round(q.y, 7), round(q.z, 7), round(q.w, 7)]


def _vec(v, digits=6):
    return [round(float(c), digits) for c in v]


def unity_skeleton(rig, meshes, root_name):
    """Rest transforms as Unity will import them, in hierarchy order (parents first).

    Entries: name, parent, local position/rotation (x, y, z, w)/scale, world
    position, and for bones the world tail (bone end) so a T-pose can be derived.
    """
    entries = []
    worlds = {}

    def add(name, parent, world_pos, world_rot, extra=None):
        if parent is None:
            local_pos, local_rot = world_pos, world_rot
        else:
            ppos, prot = worlds[parent]
            local_rot = prot.transposed() @ world_rot
            local_pos = prot.transposed() @ (world_pos - ppos)
        worlds[name] = (world_pos, world_rot)
        entry = {"name": name, "parent": parent, "position": _vec(local_pos), "rotation": _quat_xyzw(local_rot),
                 "scale": [1.0, 1.0, 1.0], "world_position": _vec(world_pos)}
        if extra:
            entry.update(extra)
        entries.append(entry)

    ident = Matrix.Identity(3)
    add(root_name, None, Vector((0.0, 0.0, 0.0)), ident.copy())
    rig_rot = rig.matrix_world.to_3x3().normalized()
    add(rig.name, root_name, TO_UNITY @ rig.matrix_world.translation, _unity_rotation(rig_rot))

    def walk(bone, parent_name):
        world = rig.matrix_world @ bone.matrix_local
        head = TO_UNITY @ world.translation
        tail = TO_UNITY @ (rig.matrix_world @ bone.tail_local)
        add(bone.name, parent_name, head, _unity_rotation(world.to_3x3().normalized()),
            {"world_tail": _vec(tail)})
        for child in bone.children:
            walk(child, bone.name)

    for bone in rig.data.bones:
        if bone.parent is None:
            walk(bone, rig.name)
    for obj in meshes:
        parent = obj.parent.name if obj.parent is not None else root_name
        world = obj.matrix_world
        add(obj.name, parent if parent in worlds else root_name, TO_UNITY @ world.translation,
            _unity_rotation(world.to_3x3().normalized()))
    return entries


def mesh_info(obj):
    keys = obj.data.shape_keys.key_blocks[1:] if obj.data.shape_keys else []
    return {
        "name": obj.name,
        "vertices": len(obj.data.vertices),
        "triangles": sum(len(p.vertices) - 2 for p in obj.data.polygons),
        "materials": [s.material.name if s.material else None for s in obj.material_slots],
        "blendshapes": [k.name for k in keys],
        "skinned": any(m.type == "ARMATURE" for m in obj.modifiers),
    }


def world_bounds(meshes):
    """Bounds of the evaluated (skinned, rest pose) meshes in world space."""
    import numpy as np

    deps = bpy.context.evaluated_depsgraph_get()
    lo, hi = np.full(3, math.inf), np.full(3, -math.inf)
    for obj in meshes:
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        ev.to_mesh_clear()
        if not len(co):
            continue
        co = co.reshape(-1, 3)
        mw = np.array(obj.matrix_world)
        world = co @ mw[:3, :3].T + mw[:3, 3]
        lo = np.minimum(lo, world.min(axis=0))
        hi = np.maximum(hi, world.max(axis=0))
    return Vector(lo), Vector(hi)


def fbx_exporter_version():
    import addon_utils

    for mod in addon_utils.modules():
        if mod.__name__.endswith("io_scene_fbx"):
            return ".".join(str(v) for v in mod.bl_info.get("version", ()))
    return None
