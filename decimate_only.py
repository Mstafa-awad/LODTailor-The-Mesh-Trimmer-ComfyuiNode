# decimate_only.py
# ULTRA-FAST MODIFIER PIPELINE (v2 — all node options now functional)
# Object-mode modifiers for heavy work; numpy rebuilds for topology cleanup;
# one small edit-mode session (on the REDUCED mesh) for repair/normals.
import argparse
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np


def log(msg):
    print(f"[FastDecimator] {msg}", flush=True)


def get_args():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--tris", type=int, default=100)
    p.add_argument("--merge-distance", type=float, default=0.0001)
    p.add_argument("--dissolve-angle", type=float, default=5.0)
    p.add_argument("--symmetry", action="store_true")
    p.add_argument("--apply-transforms", action="store_true")
    p.add_argument("--join-meshes", action="store_true")
    p.add_argument("--voxel", action="store_true")
    p.add_argument("--relative-voxel-size", type=float, default=0.0015)
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--tolerance", type=float, default=1.05)
    p.add_argument("--intermediate-ratio", type=float, default=0.5)
    p.add_argument("--last-ratio", type=float, default=0.1)
    p.add_argument("--final-ratio", type=float, default=0.05)
    p.add_argument("--triangulate", action="store_true")
    p.add_argument("--minimum-voxel-size", type=float, default=0.000001)
    p.add_argument("--cleanup-shells", action="store_true")
    p.add_argument("--min-shell-faces", type=int, default=500)
    p.add_argument("--repair", action="store_true")
    p.add_argument("--merge-by-distance", action="store_true")
    p.add_argument("--remove-loose", action="store_true")
    p.add_argument("--limited-dissolve", action="store_true")
    p.add_argument("--recalc-normals", action="store_true")
    return p.parse_args(get_args())


# ---------------------------------------------------------------- numpy helpers
_FIELD_BY_TYPE = {
    'FLOAT': ("value", 1, np.float32),
    'INT': ("value", 1, np.int32),
    'INT8': ("value", 1, np.int8),
    'BOOLEAN': ("value", 1, np.bool_),
    'FLOAT_VECTOR': ("vector", 3, np.float32),
    'FLOAT_COLOR': ("color", 4, np.float32),
    'BYTE_COLOR': ("color", 4, np.float32),
}


def _read_mesh_arrays(obj):
    me = obj.data
    nv, nf, nl = len(me.vertices), len(me.polygons), len(me.loops)
    co = np.empty(nv * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    loop_vert = np.empty(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", loop_vert)
    loop_start = np.empty(nf, dtype=np.int64)
    me.polygons.foreach_get("loop_start", loop_start)
    loop_total = np.empty(nf, dtype=np.int64)
    me.polygons.foreach_get("loop_total", loop_total)
    return me, co.reshape(nv, 3), loop_vert, loop_start, loop_total


def _rebuild_mesh(obj, keep_vert, keep_face):
    """Fast C-level rebuild keeping only kept verts/faces, preserving
    materials and POINT/CORNER attributes (UVs, vertex colors)."""
    me, co, loop_vert, loop_start, loop_total = _read_mesh_arrays(obj)
    nv, nf = len(co), len(keep_face)
    loop_mask = np.repeat(keep_face, loop_total)
    kept_loops = np.nonzero(loop_mask)[0]
    remap = np.cumsum(keep_vert) - 1
    new_loop_vert = remap[loop_vert[kept_loops]]
    new_loop_total = loop_total[keep_face]
    new_loop_start = np.concatenate(([0], np.cumsum(new_loop_total)[:-1]))
    new_co = co[keep_vert]

    new_me = bpy.data.meshes.new(obj.data.name + "_clean")
    new_me.vertices.add(int(keep_vert.sum()))
    new_me.vertices.foreach_set("co", new_co.ravel())
    new_me.loops.add(len(new_loop_vert))
    new_me.loops.foreach_set("vertex_index", new_loop_vert)
    new_me.polygons.add(int(keep_face.sum()))
    new_me.polygons.foreach_set("loop_start", new_loop_start)
    new_me.polygons.foreach_set("loop_total", new_loop_total)
    for mat in me.materials:
        new_me.materials.append(mat)
    # copy attributes
    kept_vert_idx = np.nonzero(keep_vert)[0]
    for attr in me.attributes:
        spec = _FIELD_BY_TYPE.get(attr.data_type)
        if spec is None or attr.domain not in ('POINT', 'CORNER'):
            continue
        field, comps, dt = spec
        try:
            src = np.empty(len(attr.data) * comps, dtype=dt)
            attr.data.foreach_get(field, src)
            src = src.reshape(-1, comps)
            pick = kept_vert_idx if attr.domain == 'POINT' else kept_loops
            dst_attr = new_me.attributes.new(attr.name, attr.data_type, attr.domain)
            dst_attr.data.foreach_set(field, src[pick].ravel())
        except Exception:
            continue
    new_me.update()
    old = obj.data
    obj.data = new_me
    bpy.data.meshes.remove(old)
    return len(new_me.polygons)


def _remove_loose(obj):
    me, co, loop_vert, loop_start, loop_total = _read_mesh_arrays(obj)
    used = np.zeros(len(co), dtype=bool)
    used[np.unique(loop_vert)] = True
    if used.all():
        return 0, 0
    removed = int((~used).sum())
    nf = _rebuild_mesh(obj, used, np.ones(len(loop_total), dtype=bool))
    return removed, nf


def _component_face_labels(loop_vert, loop_start, loop_total, nv):
    idx = np.arange(len(loop_vert))
    face_id = np.repeat(np.arange(len(loop_start)), loop_total)
    local = idx - loop_start[face_id]
    nxt = loop_start[face_id] + ((local + 1) % loop_total[face_id])
    a, b = loop_vert[idx], loop_vert[nxt]
    keep = a != b
    lo, hi = np.minimum(a, b)[keep], np.maximum(a, b)[keep]
    parent = np.arange(nv)
    for _ in range(128):
        ra, rb = parent[lo], parent[hi]
        np.minimum.at(parent, np.maximum(ra, rb), np.minimum(ra, rb))
        parent = parent[parent]
        if np.array_equal(parent[parent], parent) and np.array_equal(parent[lo], parent[hi]):
            break
    return parent[loop_vert[loop_start]]


def _cleanup_shells(obj, min_faces):
    me, co, loop_vert, loop_start, loop_total = _read_mesh_arrays(obj)
    labels = _component_face_labels(loop_vert, loop_start, loop_total, len(co))
    counts = np.bincount(labels, minlength=len(co))
    face_keep = counts[labels] >= int(min_faces)
    n_shells = len(np.unique(labels))
    n_kept_shells = len(np.unique(labels[face_keep])) if face_keep.any() else 0
    if face_keep.all():
        return 0, len(loop_total)
    if not face_keep.any():  # never delete everything: keep largest shell
        vals, cnts = np.unique(labels, return_counts=True)
        face_keep = labels == vals[cnts.argmax()]
        n_kept_shells = 1
    used = np.zeros(len(co), dtype=bool)
    loop_mask = np.repeat(face_keep, loop_total)
    used[np.unique(loop_vert[loop_mask])] = True
    nf = _rebuild_mesh(obj, used, face_keep)
    log(f" -> Shells: {n_shells} -> {n_kept_shells} (min_faces={min_faces})")
    return n_shells - n_kept_shells, nf


def _edit_cleanup(obj, do_repair, do_recalc, degenerate_threshold):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    if do_repair:
        bpy.ops.mesh.dissolve_degenerate(threshold=degenerate_threshold)
        bpy.ops.mesh.fill_holes(sides=0)
    if do_recalc:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')


def _apply_modifier(obj, mod, tag):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return len(obj.data.polygons)


def _weld(obj, distance, tag):
    mod = obj.modifiers.new("Weld", 'WELD')
    mod.merge_threshold = float(distance)
    tris = _apply_modifier(obj, mod, tag)
    log(f" -> Weld({tag}): {tris:,} faces")
    return tris


def _collapse(obj, ratio, symmetry, tag):
    mod = obj.modifiers.new(tag, 'DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = float(ratio)
    if symmetry:
        mod.use_symmetry = True
    tris = _apply_modifier(obj, mod, tag)
    log(f" -> {tag}: {tris:,} faces")
    return tris


def process():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)

    ext = Path(args.input).suffix.lower()
    if ext in ['.glb', '.gltf']:
        bpy.ops.import_scene.gltf(filepath=args.input)
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=args.input)
    elif ext == '.ply':
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.import_mesh.ply(filepath=args.input)
        else:
            bpy.ops.import_mesh.ply(filepath=args.input)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError("No meshes found")

    if args.apply_transforms:
        for o in meshes:
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.select_all(action='DESELECT')
            o.select_set(True)
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    if args.join_meshes and len(meshes) > 1:
        bpy.ops.object.select_all(action='SELECT')
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        meshes = [bpy.context.active_object]

    do_weld = bool(args.merge_by_distance) and float(args.merge_distance) > 0.0

    for obj in meshes:
        t0 = time.time()
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        tris = len(obj.data.polygons)
        log(f"Start: {tris:,} faces")

        # 1. MERGE BY DISTANCE on the INPUT (now respects the boolean, all branches)
        if do_weld:
            tris = _weld(obj, args.merge_distance, "input")

        # 2. LIMITED DISSOLVE (now gated by its own boolean)
        if args.limited_dissolve and args.dissolve_angle > 0:
            mod = obj.modifiers.new("Planar", 'DECIMATE')
            mod.decimate_type = 'DISSOLVE'
            mod.angle_limit = math.radians(args.dissolve_angle)
            mod.use_dissolve_boundaries = True
            tris = _apply_modifier(obj, mod, "Planar")
            log(f" -> Planar: {tris:,} faces")

        # 3. VOXEL REBUILD
        if args.voxel:
            dim = max(obj.dimensions) if max(obj.dimensions) > 0 else 1.0
            v_size = max(dim * args.relative_voxel_size, args.minimum_voxel_size)
            mod = obj.modifiers.new("Voxel", 'REMESH')
            mod.mode = 'VOXEL'
            mod.voxel_size = v_size
            tris = _apply_modifier(obj, mod, "Voxel")
            log(f" -> Voxel: {tris:,} faces")

        # 4. TRIANGULATE early so every count below is real triangles
        if args.triangulate:
            mod = obj.modifiers.new("Tri", 'TRIANGULATE')
            tris = _apply_modifier(obj, mod, "Tri")
            log(f" -> Triangulate: {tris:,} faces")

        # 5. STAGED DECIMATION (passes / tolerance / ratio ladder now used)
        target = max(4, args.tris)
        tol = max(1.0, args.tolerance)
        if tris > target * tol:
            if tris > 1_000_000:  # guard crush so huge inputs never lock
                tris = _collapse(obj, max(200_000, target) / tris, args.symmetry, "Guard")
            for p in range(max(1, args.passes)):
                if tris <= target * tol:
                    break
                remaining = args.passes - p
                if remaining >= 3:
                    floor = args.intermediate_ratio
                elif remaining == 2:
                    floor = args.last_ratio
                else:
                    floor = args.final_ratio
                ratio = min(1.0, max(floor, target / tris))
                if ratio >= 1.0:
                    break
                tris = _collapse(obj, ratio, args.symmetry, f"Pass{p + 1}")
            if tris > target * tol and tris > target:
                tris = _collapse(obj, target / tris, args.symmetry, "Final")

        # 6. MERGE BY DISTANCE on the OUTPUT (the step that was missing)
        if do_weld:
            tris = _weld(obj, args.merge_distance, "output")

        # 7. CLEANUP SHELLS (drop floater components below min_shell_faces)
        if args.cleanup_shells:
            _, tris = _cleanup_shells(obj, args.min_shell_faces)
            log(f" -> After shell cleanup: {tris:,} faces")

        # 8. REMOVE LOOSE verts/edges
        if args.remove_loose:
            removed, tris = _remove_loose(obj)
            if removed:
                log(f" -> Loose removed: {removed:,} verts | {tris:,} faces")

        # 9. REPAIR + RECALC NORMALS (one edit-mode session, on the small mesh)
        if args.repair or args.recalc_normals:
            thr = args.merge_distance if args.merge_distance > 0 else 1e-5
            _edit_cleanup(obj, bool(args.repair), bool(args.recalc_normals), thr)
            tris = len(obj.data.polygons)
            log(f" -> Repair/Normals: {tris:,} faces")

        # 10. safety triangulate in case repair created ngons
        if args.triangulate:
            me = obj.data
            if any(len(p.vertices) != 3 for p in me.polygons[:2000]):
                mod = obj.modifiers.new("Tri2", 'TRIANGULATE')
                tris = _apply_modifier(obj, mod, "Tri2")
                log(f" -> Triangulate(final): {tris:,} faces")

        log(f"Finished in {time.time() - t0:.2f} seconds")

    out_ext = Path(args.output).suffix.lower()
    bpy.ops.object.select_all(action='SELECT')
    if out_ext in ['.glb', '.gltf']:
        bpy.ops.export_scene.gltf(
            filepath=args.output, use_selection=True,
            export_format='GLB' if out_ext == '.glb' else 'GLTF_SEPARATE')
    elif out_ext == '.obj':
        bpy.ops.wm.obj_export(filepath=args.output, export_selected_objects=True)
    elif out_ext == '.ply':
        bpy.ops.wm.ply_export(filepath=args.output, export_selected_objects=True)


if __name__ == "__main__":
    try:
        process()
    except Exception as e:
        log(f"FAILED: {e}")
        sys.exit(1)