"""Skin-weight clean-up and corrections for the MPFB game_engine rig."""
import numpy as np


def weight_matrix(obj, bone_names):
    """Dense (vertices x bones) weight matrix for the given bone vertex groups."""
    index = {}
    for name in bone_names:
        group = obj.vertex_groups.get(name)
        if group is not None:
            index[group.index] = bone_names.index(name)
    weights = np.zeros((len(obj.data.vertices), len(bone_names)), dtype=np.float64)
    for vert in obj.data.vertices:
        for g in vert.groups:
            col = index.get(g.group)
            if col is not None:
                weights[vert.index, col] = g.weight
    return weights


def write_weights(obj, bone_names, weights, eps=1e-4):
    for col, name in enumerate(bone_names):
        group = obj.vertex_groups.get(name)
        column = weights[:, col]
        if group is None:
            if not (column > eps).any():
                continue
            group = obj.vertex_groups.new(name=name)
        all_idx = list(range(len(column)))
        group.remove(all_idx)
        nz = np.nonzero(column > eps)[0]
        for vid in nz:
            group.add([int(vid)], float(column[vid]), "REPLACE")


def limit_and_normalize(weights, limit=4, floor=0.01):
    """Keep the ``limit`` largest influences per vertex, drop tiny ones, renormalise to 1."""
    out = weights.copy()
    if out.shape[1] > limit:
        order = np.argsort(-out, axis=1)
        drop = order[:, limit:]
        np.put_along_axis(out, drop, 0.0, axis=1)
    out[out < floor] = 0.0
    total = out.sum(axis=1, keepdims=True)
    empty = total[:, 0] <= 0
    out[~empty] /= total[~empty]
    if empty.any():
        # A vertex without any influence would be left at the origin by a glTF viewer;
        # give it its strongest original influence.
        best = np.argmax(weights[empty], axis=1)
        out[np.nonzero(empty)[0], best] = 1.0
    return out


def neighbours(mesh):
    """Vertex adjacency lists from the mesh edges."""
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    adj = [[] for _ in range(len(mesh.vertices))]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    return adj


def smooth(weights, adjacency, mask, iterations=4, factor=0.5, columns=None):
    """Laplacian smoothing of the weight rows of the vertices in ``mask``.

    ``columns`` restricts smoothing to some bones (others keep their weights,
    the smoothed ones are rescaled into the remaining share).
    """
    out = weights.copy()
    verts = np.nonzero(mask)[0]
    cols = np.arange(out.shape[1]) if columns is None else np.asarray(columns)
    for _ in range(iterations):
        new = out.copy()
        for v in verts:
            nb = adjacency[v]
            if not nb:
                continue
            avg = out[nb][:, cols].mean(axis=0)
            new[v, cols] = out[v, cols] * (1 - factor) + avg * factor
        out = new
    if columns is not None:
        others = np.setdiff1d(np.arange(out.shape[1]), cols)
        share = 1.0 - out[:, others].sum(axis=1)
        part = out[:, cols].sum(axis=1)
        scale = np.where(part > 1e-9, np.clip(share, 0, 1) / np.maximum(part, 1e-9), 0.0)
        out[np.ix_(verts, cols)] *= scale[verts, None]
    return out
