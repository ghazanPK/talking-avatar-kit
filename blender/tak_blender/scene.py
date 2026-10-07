"""Create the MPFB character described by a spec (body, rig, proxies, face targets)."""
from importlib import import_module
from pathlib import Path

import bpy
import numpy as np


class Mpfb:
    """Thin access to the MPFB services and entities of the enabled extension."""

    def __init__(self, package):
        services = import_module(package.__name__ + ".services")
        self.HumanService = services.HumanService
        self.AssetService = services.AssetService
        self.FaceService = services.FaceService
        self.ExportService = services.ExportService
        self.ClothesService = services.ClothesService
        self.LocationService = services.LocationService
        face = import_module(package.__name__ + ".services.faceservice")
        self.ARKIT = list(face.ARKIT_FACEUNITS)
        self.VISEMES = list(face.META_VISEMES)
        self.Mhclo = import_module(package.__name__ + ".entities.clothes.mhclo").Mhclo
        self.user_data = Path(self.LocationService.get_user_data())

    def find(self, category, stem, material=False):
        """Absolute path of an installed asset by name, preferring the kit's own user data."""
        items = (self.AssetService.list_mhmat_assets(category) if material
                 else self.AssetService.list_mhclo_assets(category))
        matches = [Path(str(p)) for p in items if Path(str(p)).stem.lower() == stem.lower()]
        if not matches:
            raise LookupError(f"MPFB asset '{stem}' not found in category '{category}'")
        matches.sort(key=lambda p: 0 if self.user_data in p.parents else 1)
        return str(matches[0])

    def eye_material(self, name):
        path = self.user_data / "eyes" / "materials" / f"{name}.mhmat"
        if not path.is_file():
            raise LookupError(f"eye material '{name}' not found")
        return path


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures, bpy.data.images,
                  bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def create_body(mpfb, spec):
    body = spec["body"]
    macro = {k: float(body[k]) for k in ("gender", "age", "muscle", "weight", "height",
                                         "proportions", "cupsize", "firmness")}
    macro["race"] = {k: float(v) for k, v in body["race"].items()}
    base = mpfb.HumanService.create_human(mask_helpers=True, detailed_helpers=True,
                                          extra_vertex_groups=True, feet_on_ground=True,
                                          scale=0.1, macro_detail_dict=macro)
    mpfb.HumanService.set_character_skin(mpfb.find("skins", spec["skin"]["material"], True), base,
                                         skin_type="GAMEENGINE", material_instances=False)
    return base


def add_rig(mpfb, base, rig_name):
    return mpfb.HumanService.add_builtin_rig(base, rig_name, import_weights=True)


def add_proxy(mpfb, base, category, stem):
    path = mpfb.find(category, stem)
    obj = mpfb.HumanService.add_mhclo_asset(path, base, asset_type=category, subdiv_levels=0,
                                            material_type="GAMEENGINE", set_up_rigging=True,
                                            interpolate_weights=True, import_subrig=True,
                                            import_weights=True)
    obj["tak_mhclo"] = path
    return obj


def load_face_targets(mpfb, base):
    mpfb.FaceService.load_targets(base, load_microsoft_visemes=False, load_meta_visemes=True,
                                  load_arkit_faceunits=True)
    names = set(base.data.shape_keys.key_blocks.keys())
    missing = [n for n in mpfb.ARKIT + mpfb.VISEMES if n not in names]
    if missing:
        raise RuntimeError(f"face targets missing after loading: {missing}")


def bake_macro_shapes(base):
    """Freeze MPFB proportion targets into the basis so fitted proxies stay aligned in glTF.

    MPFB keeps ``$md-...`` macro keys active; leaving them as morph targets would
    move the body away from its proxies in a glTF viewer.
    """
    keys = base.data.shape_keys.key_blocks
    macros = [key for key in keys if key.name.startswith("$")]
    if not macros:
        return
    count = len(base.data.vertices)
    basis = np.empty(count * 3, dtype=np.float32)
    keys[0].data.foreach_get("co", basis)
    displacement = np.zeros_like(basis)
    scratch = np.empty_like(basis)
    for key in macros:
        if key.value:
            key.data.foreach_get("co", scratch)
            displacement += (scratch - basis) * key.value
    for key in keys:
        if key not in macros:
            key.data.foreach_get("co", scratch)
            key.data.foreach_set("co", scratch + displacement)
    for key in reversed(macros):
        base.shape_key_remove(key)
    base.data.update()


def transfer_face_targets(mpfb, base, proxy, names, threshold=1e-4):
    """Give a fitted proxy the face targets of the body through its MHCLO binding.

    Each proxy vertex is a weighted sum of three body vertices (plus an offset),
    so a body target's deltas map directly onto the proxy: lashes follow blinks,
    teeth and tongue follow the jaw, eyeballs follow the eye-look targets.
    Must run before helper geometry is removed. Returns the names added.
    """
    mh = mpfb.Mhclo()
    mh.load(proxy["tak_mhclo"])
    count = len(proxy.data.vertices)
    if len(mh.verts) != count:
        raise RuntimeError(f"{proxy.name}: MHCLO has {len(mh.verts)} vertices, mesh has {count}")
    refs = np.array([mh.verts[i]["verts"] for i in range(count)], dtype=np.int64)
    weights = np.array([mh.verts[i]["weights"] for i in range(count)], dtype=np.float64)

    keys = base.data.shape_keys.key_blocks
    nbase = len(base.data.vertices)
    basis = np.empty(nbase * 3, dtype=np.float32)
    keys[0].data.foreach_get("co", basis)
    basis = basis.reshape(-1, 3).astype(np.float64)
    to_world = np.array(base.matrix_world.to_3x3())
    to_proxy = np.linalg.inv(np.array(proxy.matrix_world.to_3x3()))
    linear = to_proxy @ to_world

    if proxy.data.shape_keys is None:
        proxy.shape_key_add(name="Basis", from_mix=False)
    pbasis = np.empty(count * 3, dtype=np.float32)
    proxy.data.shape_keys.key_blocks[0].data.foreach_get("co", pbasis)
    pbasis = pbasis.reshape(-1, 3)
    scratch = np.empty(nbase * 3, dtype=np.float32)
    added = []
    for name in names:
        keys[name].data.foreach_get("co", scratch)
        delta = scratch.reshape(-1, 3) - basis
        moved = np.einsum("vk,vkc->vc", weights, delta[refs]) @ linear.T
        if np.abs(moved).max() < threshold:
            continue
        key = proxy.shape_key_add(name=name, from_mix=False)
        key.value = 0.0
        key.data.foreach_set("co", (pbasis + moved).astype(np.float32).ravel())
        added.append(name)
    if not added:
        proxy.shape_key_clear()
    return added


def remove_eye_shell(eyes, u_min=0.85, v_max=0.15):
    """Delete the outer transparent shell of the MakeHuman high-poly eyes.

    That shell is UV-mapped onto the small disc in the corner of the eye
    texture and relies on alpha blending; rendered opaque it hides the iris.
    The wet look comes from the eyeball's clearcoat instead. Shape keys and
    vertex groups are kept (BMesh round trip).
    """
    import bmesh
    mesh = eyes.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv = bm.loops.layers.uv.active
    doomed = [f for f in bm.faces
              if all(l[uv].uv.x > u_min and l[uv].uv.y < v_max for l in f.loops)]
    if doomed and len(doomed) < len(bm.faces):
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(mesh)
        mesh.update()
    bm.free()
    return len(doomed)


def tuck_under(inner, outer, margin=0.006, reach=0.03):
    """Push vertices of an inner garment (e.g. socks of a shoe) below an outer one (trousers).

    MakeHuman garments are fitted independently, so a sock can poke through a
    trouser leg. Every inner vertex closer than ``reach`` to the outer surface
    (away from its open borders) and not at least ``margin`` beneath it is
    moved inward along the outer surface normal. Run in the rest pose on a
    mesh without shape keys. Returns the number of vertices moved.
    """
    if inner.data.shape_keys:
        return 0
    from mathutils import Vector
    from mathutils.kdtree import KDTree

    o_world = outer.matrix_world
    o_normal = o_world.to_3x3().inverted().transposed()
    tree = KDTree(len(outer.data.vertices))
    normals = []
    for v in outer.data.vertices:
        tree.insert(o_world @ v.co, v.index)
        normals.append((o_normal @ v.normal).normalized())
    tree.balance()
    # Vertices on open borders (hems, cuffs): the inner garment may legitimately pass there.
    border = set()
    edge_faces = {}
    for poly in outer.data.polygons:
        for key in poly.edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    for (a, b), count in edge_faces.items():
        if count == 1:
            border.update((a, b))
    i_world = inner.matrix_world
    i_inv = i_world.inverted()
    moved = 0
    for v in inner.data.vertices:
        p = i_world @ v.co
        hits = tree.find_n(p, 4)
        if not hits or hits[0][2] > reach or any(index in border for _, index, _ in hits):
            continue
        normal = Vector((0, 0, 0))
        anchor = Vector((0, 0, 0))
        for co, index, dist in hits:
            normal += normals[index]
            anchor += co
        normal.normalize()
        anchor /= len(hits)
        depth = (p - anchor).dot(normal)  # > 0: outside the outer garment
        if depth > -margin:
            v.co = i_inv @ (p - normal * (depth + margin))
            moved += 1
    inner.data.update()
    return moved


def remove_helpers(mpfb, base):
    mpfb.ExportService.bake_modifiers_remove_helpers(base, bake_masks=True, bake_subdiv=False,
                                                     remove_helpers=True, also_proxy=False)


def descendants(root):
    result, stack = [root], [root]
    while stack:
        for child in stack.pop().children:
            result.append(child)
            stack.append(child)
    return result
