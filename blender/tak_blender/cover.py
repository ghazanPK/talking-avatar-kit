"""Remove the body under garments that do not say what they cover.

MakeHuman's own garments carry a ``delete_verts`` list, which MPFB turns into
the mask that hides the body underneath (baked by ``scene.remove_helpers``).
Several community garments (the cargo pants, the polo shirt, the knitted
sweater, the long skirt) carry none, so the whole body stays under them and a
chest, knee or shoulder pushes through the fabric as soon as a pose stretches
it. This finds the covered body the way a person would: look outward from each
body vertex, and if the garment is right there, the skin is covered.

Per garment, the spec's ``cover`` setting chooses: ``auto`` (default: only
garments without a delete list are ray-cast), ``raycast`` (always, in addition
to any delete list) or ``none``.
"""
import bmesh
from mathutils.bvhtree import BVHTree

#: A garment further out than this from the skin is not covering it (metres).
REACH = 0.06
#: Rays start this far inside the skin, so a garment already sunk into it still counts.
INSIDE = 0.01
#: Rings of covered vertices kept along each edge of the covered area, so a hem that
#: lifts with the arm or a turn of the head never opens onto a hole.
MARGIN_RINGS = 2


def has_delete_list(mhclo_path):
    with open(mhclo_path, encoding="utf-8", errors="replace") as handle:
        return any(line.startswith("delete_verts") for line in handle)


def _world_tree(obj):
    points = [obj.matrix_world @ v.co for v in obj.data.vertices]
    polygons = [list(p.vertices) for p in obj.data.polygons]
    return BVHTree.FromPolygons(points, polygons)


def covered_by(body, garment, reach=REACH, inside=INSIDE):
    """Indices of body vertices with this garment just outside them."""
    tree = _world_tree(garment)
    to_world = body.matrix_world
    normal_matrix = to_world.to_3x3().inverted().transposed()
    covered = set()
    for vertex in body.data.vertices:
        normal = (normal_matrix @ vertex.normal).normalized()
        origin = to_world @ vertex.co - normal * inside
        hit, _, _, _ = tree.ray_cast(origin, normal, reach + inside)
        if hit is not None:
            covered.add(vertex.index)
    return covered


def erode(mesh, covered, rings):
    """Drop the outermost ``rings`` rings of the covered set."""
    neighbours = {index: set() for index in range(len(mesh.vertices))}
    for edge in mesh.edges:
        a, b = edge.vertices
        neighbours[a].add(b)
        neighbours[b].add(a)
    for _ in range(rings):
        border = {i for i in covered if any(o not in covered for o in neighbours[i])}
        covered = covered - border
    return covered


def wants_raycast(item, mhclo_path):
    mode = item.get("cover", "auto")
    if mode == "none":
        return False
    if mode == "raycast":
        return True
    return not has_delete_list(mhclo_path)


def delete_covered(body, clothes):
    """Remove body faces wholly under the chosen garments; keeps shape keys and attributes.

    ``clothes`` is a list of (spec item, garment object) pairs; each object carries its
    MHCLO path in ``obj["tak_mhclo"]``. Returns {"garments": [...], "faces_deleted": n}.
    """
    covered = set()
    used = []
    for item, garment in clothes:
        if wants_raycast(item, garment["tak_mhclo"]):
            covered |= covered_by(body, garment)
            used.append(item["asset"])
    covered = erode(body.data, covered, MARGIN_RINGS)
    if not covered:
        return {"garments": used, "faces_deleted": 0}
    mesh = body.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    doomed = [f for f in bm.faces if all(v.index in covered for v in f.verts)]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return {"garments": used, "faces_deleted": len(doomed)}
