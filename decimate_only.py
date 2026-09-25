"""
ULTRA-FAST DECIMATION PIPELINE (v5.2)
- NO smoothing anywhere (flat shading forced, flat normals exported).
- FINAL step = Blender "Merge by Distance" with CENTROID MERGE (same as UI),
  applied at the END, increasing by the user's base distance until watertight.
"""
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
    p.add_argument("--tris", type=int, default=60000)
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--tolerance", type=float, default=1.05)
    p.add_argument("--intermediate-ratio", type=float, default=0.5)
    p.add_argument("--last-ratio", type=float, default=0.25)
    p.add_argument("--final-ratio", type=float, default=0.2)
    p.add_argument("--triangulate", action="store_true")
    p.add_argument("--symmetry", action="store_true")
    p.add_argument("--voxel", action="store_true")
    p.add_argument("--relative-voxel-size", type=float, default=0.0015)
    p.add_argument("--minimum-voxel-size", type=float, default=0.000001)
    p.add_argument("--seal-distance", type=float, default=0.0001)
    p.add_argument("--seal-max-steps", type=int, default=100)
    p.add_argument("--seal-keep-trying", action="store_true")
    return p.parse_args(get_args())


# ------------------------------------------------------------------ analysis
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


def _edge_stats(obj):
    """Return (boundary_edges, non_manifold_edges). Watertight == (0, 0)."""
    me, co, loop_vert, loop_start, loop_total = _read_mesh_arrays(obj)

    nv = len(co)
    idx = np.arange(len(loop_vert))

    face_id = np.repeat(np.arange(len(loop_start)), loop_total)
    local = idx - loop_start[face_id]
    nxt = loop_start[face_id] + ((local + 1) % loop_total[face_id])

    a, b = loop_vert[idx], loop_vert[nxt]

    keep = a != b
    lo = np.minimum(a, b)[keep]
    hi = np.maximum(a, b)[keep]

    keys = lo * np.int64(nv) + hi
    _, counts = np.unique(keys, return_counts=True)

    boundary = int(np.count_nonzero(counts == 1))
    nonmanifold = int(np.count_nonzero(counts > 2))

    return boundary, nonmanifold


# ------------------------------------------------------------------ editing
def _set_active(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)


def _apply_modifier(obj, mod, tag):
    _set_active(obj)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return len(obj.data.polygons)


def _weld(obj, distance, tag):
    mod = obj.modifiers.new("Weld", 'WELD')
    mod.merge_threshold = float(distance)
    return _apply_modifier(obj, mod, tag)


def _collapse(obj, ratio, symmetry, tag):
    mod = obj.modifiers.new(tag, 'DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = float(ratio)

    if symmetry:
        mod.use_symmetry = True

    tris = _apply_modifier(obj, mod, tag)
    log(f" -> {tag}: {tris:,} faces")
    return tris


def _adaptive_seal(obj, start, max_steps, tag):
    """Cheap input-side seal (old safe behavior: stops when no improvement)."""
    dist = max(float(start), 1e-7)
    step = dist

    diag = math.sqrt(sum(d * d for d in obj.dimensions)) or 1.0
    cap = diag * 0.005

    b, nm = _edge_stats(obj)
    log(f" -> Seal[{tag}] pre-weld: boundary={b:,} nonmanifold={nm:,}")

    if b == 0 and nm == 0:
        log(f" -> Seal[{tag}] already watertight+manifold")
        return dist, True

    sealed = False
    i = 0

    while i < int(max_steps) and dist <= cap:
        prev_me = obj.data.copy()

        _weld(obj, dist, f"seal-{tag}-{i + 1}")

        b2, nm2 = _edge_stats(obj)
        log(f" -> Seal[{tag}] step {i + 1}: distance={dist:.6f} "
            f"boundary={b2:,} nonmanifold={nm2:,}")

        if b2 == 0 and nm2 == 0:
            bpy.data.meshes.remove(prev_me)
            sealed = True
            log(f" -> Seal[{tag}] SEALED at distance={dist:.6f}")
            break

        if (b2 + nm2) >= (b + nm):
            bad = obj.data
            obj.data = prev_me
            bpy.data.meshes.remove(bad)
            log(f" -> Seal[{tag}] no improvement, reverted step")
            break

        bpy.data.meshes.remove(prev_me)

        b, nm = b2, nm2
        dist += step
        i += 1

    if not sealed:
        log(f" -> Seal[{tag}] WARNING: boundary={b:,} nonmanifold={nm:,} "
            f"after {i} steps (cap={cap:.6f})")

    return dist, sealed


# ------------------------------------------- Merge by Distance + Centroid Merge
def _centroid_merge_kwargs():
    """
    Detect the 'Centroid Merge' checkbox of bpy.ops.mesh.remove_doubles
    at runtime (same option you ticked in the UI panel).
    """
    try:
        rna = bpy.ops.mesh.remove_doubles.get_rna_type()
        for prop in rna.properties:
            label = (prop.name or "").lower()
            ident = (prop.identifier or "").lower()
            if "centroid" in label or "centroid" in ident:
                return {prop.identifier: True}
    except Exception:
        pass
    return {}


def _merge_by_distance_centroid(obj, distance, tag):
    """
    EXACT equivalent of your UI operation:
    Merge by Distance, Centroid Merge = ON, all verts selected.
    """
    _set_active(obj)
    try:
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        kwargs = {"threshold": float(distance)}
        kwargs.update(_centroid_merge_kwargs())

        bpy.ops.mesh.remove_doubles(**kwargs)
        bpy.ops.object.mode_set(mode='OBJECT')

        return len(obj.data.polygons)
    except Exception as e:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
        log(f" -> {tag}: remove_doubles failed ({e}), fallback Weld modifier")
        mod = obj.modifiers.new("Weld", 'WELD')
        mod.merge_threshold = float(distance)
        return _apply_modifier(obj, mod, tag)


def _final_watertight_merge(obj, base, max_steps, keep_trying, tag="output"):
    """
    Applied AT THE END.
    0.0001 -> 0.0002 -> 0.0003 ... (base * step)
    Stops only when boundary == 0 and nonmanifold == 0,
    or when max_steps / safety cap is reached.
    """
    base = max(float(base), 1e-7)
    max_steps = max(1, int(max_steps))

    diag = math.sqrt(sum(d * d for d in obj.dimensions)) or 1.0
    cap = max(diag * 0.005, base * float(max_steps)) if keep_trying else diag * 0.005

    b, nm = _edge_stats(obj)
    log(f" -> Merge[{tag}] pre: boundary={b:,} nonmanifold={nm:,} "
        f"keep_trying={keep_trying}")

    if b == 0 and nm == 0:
        log(f" -> Merge[{tag}] already watertight")
        return base, True

    sealed = False
    last = base
    steps = max_steps if keep_trying else 1

    for step_i in range(1, steps + 1):
        dist = round(base * float(step_i), 12)

        if dist > cap:
            log(f" -> Merge[{tag}] safety cap reached ({cap:.6f})")
            break

        last = dist
        _merge_by_distance_centroid(obj, dist, f"Merge[{tag}] step {step_i}")

        b2, nm2 = _edge_stats(obj)
        log(f" -> Merge[{tag}] step {step_i}: distance={dist:.6f} "
            f"boundary={b2:,} nonmanifold={nm2:,}")

        if b2 == 0 and nm2 == 0:
            sealed = True
            log(f" -> Merge[{tag}] WATERTIGHT at distance={dist:.6f}")
            break

    if not sealed:
        b, nm = _edge_stats(obj)
        log(f" -> Merge[{tag}] NOT watertight after loop: "
            f"boundary={b:,} nonmanifold={nm:,}")

    return last, sealed


# ------------------------------------------------------------------ main
def process():
    args = parse_args()

    bpy.ops.wm.read_factory_settings(use_empty=True)

    ext = Path(args.input).suffix.lower()

    if ext in ['.glb', '.gltf']:
        bpy.ops.import_scene.gltf(filepath=args.input)
    elif ext == '.obj':
        try:
            bpy.ops.wm.obj_import(filepath=args.input)
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=args.input)
    elif ext == '.ply':
        bpy.ops.import_mesh.ply(filepath=args.input)
    else:
        raise RuntimeError(f"Unsupported input type: {ext}")

    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError("No meshes found")

    for o in meshes:
        _set_active(o)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    if len(meshes) > 1:
        bpy.ops.object.select_all(action='SELECT')
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        meshes = [bpy.context.active_object]

    for obj in meshes:
        t0 = time.time()

        _set_active(obj)
        tris = len(obj.data.polygons)
        log(f"Start: {tris:,} faces")

        # 1. cheap input seal
        _adaptive_seal(obj, args.seal_distance, args.seal_max_steps, "input")

        # 2. voxel rebuild
        if args.voxel:
            dim = max(obj.dimensions) if max(obj.dimensions) > 0 else 1.0
            v_size = max(dim * args.relative_voxel_size, args.minimum_voxel_size)

            mod = obj.modifiers.new("Voxel", 'REMESH')
            mod.mode = 'VOXEL'
            mod.voxel_size = v_size

            tris = _apply_modifier(obj, mod, "Voxel")
            log(f" -> Voxel: {tris:,} faces")

        # 3. triangulate
        if args.triangulate:
            mod = obj.modifiers.new("Tri", 'TRIANGULATE')
            tris = _apply_modifier(obj, mod, "Tri")
            log(f" -> Triangulate: {tris:,} faces")

        # 4. staged decimation
        target = max(4, args.tris)
        tol = max(1.0, args.tolerance)
        SAFE_FLOOR = 0.15

        if tris > target * tol:
            if tris > 1_000_000:
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

                floor = max(floor, SAFE_FLOOR)
                ratio = min(1.0, max(floor, target / tris))

                if ratio >= 1.0:
                    break

                tris = _collapse(obj, ratio, args.symmetry, f"Pass{p + 1}")

            guard = 0
            while tris > target * tol and tris > target and guard < 6:
                tris = _collapse(obj, max(0.25, target / tris), args.symmetry, f"Final{guard + 1}")
                guard += 1

        # 5. safety triangulate (merge can leave ngons)
        if args.triangulate:
            me = obj.data
            if any(len(p.vertices) != 3 for p in me.polygons[:2000]):
                mod = obj.modifiers.new("Tri2", 'TRIANGULATE')
                tris = _apply_modifier(obj, mod, "Tri2")
                log(f" -> Triangulate(final): {tris:,} faces")

        # 6. FINAL: Merge by Distance (Centroid Merge) until watertight
        _final_watertight_merge(
            obj,
            args.seal_distance,
            args.seal_max_steps,
            args.seal_keep_trying,
            "output",
        )

        tris = len(obj.data.polygons)
        b, nm = _edge_stats(obj)

        log(f"FINAL: {tris:,} faces | boundary={b:,} nonmanifold={nm:,} "
            f"| watertight={'YES' if (b == 0 and nm == 0) else 'NO'}")
        log(f"Finished in {time.time() - t0:.2f} seconds")

    # 7. NO SMOOTHING. Force flat shading + kill custom split normals.
    for obj in meshes:
        try:
            _set_active(obj)
            bpy.ops.mesh.custom_splitnormals_clear()
        except Exception:
            pass

        n = len(obj.data.polygons)
        if n:
            obj.data.polygons.foreach_set("use_smooth", np.zeros(n, dtype=bool))
            obj.data.update()

    # 8. export WITH normals so the flat shading survives the GLB round-trip.
    out_ext = Path(args.output).suffix.lower()

    bpy.ops.object.select_all(action='SELECT')

    if out_ext in ['.glb', '.gltf']:
        bpy.ops.export_scene.gltf(
            filepath=args.output, use_selection=True,
            export_format='GLB' if out_ext == '.glb' else 'GLTF_SEPARATE')
    elif out_ext == '.obj':
        try:
            bpy.ops.wm.obj_export(filepath=args.output, export_selected_objects=True)
        except AttributeError:
            bpy.ops.export_scene.obj(filepath=args.output, use_selection=True)
    elif out_ext == '.ply':
        bpy.ops.wm.ply_export(filepath=args.output, export_selected_objects=True)
    else:
        raise RuntimeError(f"Unsupported output type: {out_ext}")


if __name__ == "__main__":
    try:
        process()
    except Exception as e:
        log(f"FAILED: {e}")
        sys.exit(1)