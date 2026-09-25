# LODTailor — The Mesh Trimmer

LODTailor is a **ComfyUI mesh optimization and LOD utility** that sends mesh processing to Blender as an external, headless worker.

It is designed for **large AI-generated 3D meshes** where you need fast face-count reduction, optional voxel rebuilding, and a final Merge by Distance pass to clean and seal the result.

---

## Demo

### Sword

<video src="Doc/sword.mp4" controls width="100%"></video>

[▶ Open sword demo](Doc/sword.mp4)

### Weapon

<video src="Doc/weapong.mp4" controls width="100%"></video>

[▶ Open weapon demo](Doc/weapong.mp4)

---

## What it does

LODTailor takes a ComfyUI `MESH`, extracts or converts the geometry to a temporary mesh file, runs Blender in background mode, and rebuilds the processed result as a ComfyUI-compatible `MESH`.

The current pipeline is built around:

- **Blender native modifiers/operators** for the heavy geometry work
- **Staged Decimate reduction** instead of one giant reduction step
- **Large-mesh guard reduction** for meshes above 1,000,000 faces
- **Optional voxel remeshing**
- **Adaptive input-side welding/sealing**
- **Final Merge by Distance with Centroid Merge**
- **Flat-shaded output with custom split normals cleared**
- **Automatic temporary-file cleanup**

---

## Processing pipeline

1. Accept a ComfyUI `MESH` or compatible mesh-like input.
2. Extract an existing mesh path, GLB bytes, arrays, dictionary/object data, or an exportable mesh object.
3. Convert array-based inputs to a temporary GLB or OBJ when necessary.
4. Start Blender with `--background --python decimate_only.py`.
5. Apply object transforms.
6. Join multiple imported mesh objects into one object.
7. Run an **adaptive input seal** using Blender welding and edge checks.
8. Optionally run **voxel remeshing**.
9. Optionally **triangulate**.
10. Run staged **Decimate / Collapse** passes.
11. Apply a final safety triangulation when non-triangular polygons remain.
12. Run the **final Merge by Distance** stage using Centroid Merge when available.
13. Check boundary and non-manifold edges after the final merge.
14. Clear custom split normals and force **flat shading**.
15. Export the processed mesh and rebuild the ComfyUI `MESH`.
16. Remove the temporary processing directory.

> **Important:** this version intentionally does **not** preserve smooth/generated vertex normals. The Blender worker clears custom split normals and forces polygons to flat shading. Vertex colors and UVs are carried through when they are available and survive the selected conversion path.

---

## Main features

### ComfyUI-native mesh handling

The node is designed around the ComfyUI `MESH` type and attempts to reconstruct the official ComfyUI mesh class when available.

The input conversion layer supports common representations such as:

- ComfyUI mesh objects
- File paths
- GLB bytes
- NumPy arrays
- PyTorch tensors
- `(vertices, faces)` tuples/lists
- Dictionaries containing mesh data
- Objects exposing mesh/data/model/object fields
- trimesh-like objects exposing `export()` or `write()`

Common geometry field names are also detected automatically, including `vertices`, `verts`, `positions`, `points`, `faces`, `tris`, `triangles`, UV fields, and vertex-color fields.

### Headless Blender worker

Blender is launched externally in background mode:

```text
blender --background --python decimate_only.py -- ...
```

No visible Blender UI is required. The ComfyUI node waits for the Blender process to finish, then loads the output.

### Native Blender geometry operations

The current Blender script uses native Blender operations for the main stages:

- `WELD`
- `REMESH` with voxel mode
- `DECIMATE` with collapse mode
- `TRIANGULATE`
- `Merge by Distance` / `remove_doubles`

### Large-mesh guard

When the mesh has more than **1,000,000 faces**, LODTailor performs an initial guard reduction before the normal multi-pass decimation.

This reduces the amount of geometry that the later target-driven passes need to process.

### Staged target reduction

The node can run several Decimate passes. Earlier passes use `intermediate_ratio`, later passes use `last_ratio` and `final_ratio`, and the normal pass ratios are protected by a minimum safety floor of `0.15`.

A final reduction loop can continue after the regular passes until the result is within the requested target tolerance.

### Optional voxel rebuild

Voxel rebuilding can be enabled when the generated mesh needs surface consolidation before decimation.

The voxel size is calculated from the mesh's largest dimension:

```text
voxel_size = max(max_dimension * relative_voxel_size, minimum_voxel_size)
```

### Final Centroid Merge sealing

The final merge is intentionally performed **after decimation**.

When available in the installed Blender version, LODTailor detects Blender's **Centroid Merge** option and enables it for the Merge by Distance operation.

With `seal_keep_trying=True`, the merge distance is increased step-by-step:

```text
base
base × 2
base × 3
...
base × N
```

After each step the script checks:

```text
boundary edges
non-manifold edges
```

The mesh is considered watertight/manifold by this pipeline when both counts are zero.

A dimension-based safety cap and the configured maximum number of steps prevent the merge distance from growing without limit.

### Flat-shaded output

After all geometry processing, the worker:

1. Clears custom split normals when possible.
2. Disables `use_smooth` on all polygons.
3. Exports the mesh with Blender-generated flat normals.

This prevents the output from becoming globally shade-smooth because of automatically generated smooth normals.

---

## Node

**Display name:** `LODTailor The Mesh Trimmer`  
**Category:** `LODsmith`  
**Output:** `MESH`

### Parameters

| Parameter | Type | Default | Description |
|---|---|---:|---|
| `mesh` | `MESH` | — | Input ComfyUI mesh or compatible mesh-like object. |
| `blender_path` | `STRING` | `blender` | Blender executable or full path to it. |
| `target_tris` | `INT` | `60000` | Requested target face count. With triangulation enabled, these faces are triangles. |
| `passes` | `INT` | `3` | Number of regular Decimate passes. |
| `tolerance` | `FLOAT` | `1.05` | Stops regular reduction when faces are at or below `target_tris × tolerance`. |
| `intermediate_ratio` | `FLOAT` | `0.50` | Reduction floor used for earlier passes. |
| `last_ratio` | `FLOAT` | `0.25` | Reduction floor when two passes remain. |
| `final_ratio` | `FLOAT` | `0.20` | Reduction floor for the final regular pass. |
| `triangulate` | `BOOLEAN` | `True` | Triangulate geometry before reduction and run a final safety triangulation when needed. |
| `symmetry` | `BOOLEAN` | `False` | Enable Decimate modifier symmetry. |
| `voxel_rebuild` | `BOOLEAN` | `True` | Enable Blender voxel remeshing before decimation. |
| `relative_voxel_size` | `FLOAT` | `0.0015` | Voxel size relative to the mesh's largest dimension. |
| `minimum_voxel_size` | `FLOAT` | `0.000001` | Minimum voxel size. |
| `seal_distance` | `FLOAT` | `0.0001` | Base distance used by the input seal and final Merge by Distance stage. |
| `seal_max_steps` | `INT` | `100` | Maximum number of merge/seal steps. |
| `seal_keep_trying` | `BOOLEAN` | `True` | Keep increasing the final merge distance instead of doing only one step. |
| `timeout_seconds` | `INT` | `1800` | Blender process timeout in seconds. `0` disables the timeout. |

### Input ranges

| Parameter | Range |
|---|---|
| `target_tris` | `1` → `10,000,000` |
| `passes` | `1` → `1000` |
| `tolerance` | `1.0` → `2.0` |
| `intermediate_ratio` / `last_ratio` / `final_ratio` | `0.001` → `1.0` |
| `relative_voxel_size` | `0.00001` → `0.1` |
| `minimum_voxel_size` | `0.000001` → `1.0` |
| `seal_distance` | `0.000001` → `0.1` |
| `seal_max_steps` | `1` → `1000` |
| `timeout_seconds` | `0` → `86400` |

---

## Important behavior

### `target_tris` is a target, not an exact guarantee

The parameter is the requested target. The final face count can differ because of decimation behavior, tolerance, triangulation, and the final Merge by Distance stage.

The script internally works with Blender polygon/face counts. When `triangulate=True`, the processed mesh is expected to be triangular.

### The final merge can change topology and face count

Because Merge by Distance is the final stage, it can change vertices and topology **after** decimation. This is intentional.

### Watertightness is based on edge counts

The current worker treats the result as watertight/manifold when:

```text
boundary_edges == 0
non_manifold_edges == 0
```

The script logs these values during the input seal and final merge stages.

### Voxel rebuilding is not lossless

Voxel remeshing rebuilds the surface at the selected voxel resolution. It can therefore alter small details and topology.

### Smooth normals are not preserved

This is intentional in the current version. The output is forced to flat shading rather than carrying smooth normals generated by trimesh or another conversion step.

---

## Supported formats

The Blender worker currently handles:

```text
GLB
GLTF
OBJ
PLY
```

For some ComfyUI mesh inputs, the wrapper first converts the data to a temporary GLB or OBJ before sending it to Blender.

---

## Installation

Clone or copy the repository into your ComfyUI `custom_nodes` directory:

```text
ComfyUI/custom_nodes/LODTailor-The-Mesh-Trimmer-ComfyuiNode
```

### Git

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Mstafa-awad/LODTailor-The-Mesh-Trimmer-ComfyuiNode.git
```

Restart ComfyUI after installation.

The node appears as:

```text
LODsmith → LODTailor The Mesh Trimmer
```

---

## Blender setup

Blender is required as an external application.

The default value is:

```text
blender
```

This works when `blender` is available in the system `PATH`.

For a custom Blender installation, set `blender_path` to the executable, for example:

```text
C:\Program Files\Blender Foundation\Blender 4.x\blender.exe
```

---

## Python dependencies

LODTailor does not bundle Blender or ComfyUI.

The wrapper uses:

- **NumPy** for array conversion
- **trimesh** for mesh loading/conversion

These are expected to be available in the ComfyUI Python environment.

No additional pip installation is intentionally required by the current node beyond the environment it runs inside.

---

## Output handling

The output is returned as:

```text
MESH
```

The wrapper attempts to preserve the original ComfyUI mesh object structure when possible and replaces its geometry with the processed result.

The output reconstruction can carry:

- Vertices
- Faces
- Vertex colors when available
- UVs when available

Normals are intentionally set to `None` in the reconstructed mesh because the Blender worker outputs flat-shaded geometry rather than smooth vertex normals.

The loader also attempts a post-import vertex merge to undo unnecessary glTF vertex splits.

For diagnostics, the loader reports values such as:

```text
watertight
winding_consistent
body_count
Euler number
```

and the Blender worker reports:

```text
face count
boundary edge count
non-manifold edge count
watertight status
processing time
```

---

## Typical workflow

```text
AI 3D Generation
        ↓
     MESH output
        ↓
LODTailor The Mesh Trimmer
        ↓
 optional voxel rebuild
 staged decimation
 final Merge by Distance
 flat shading
        ↓
    MESH output
        ↓
UV / baking / texturing / export / game-engine processing
```

LODTailor is intended to be a geometry-reduction stage inside a larger ComfyUI 3D pipeline.

---

## Why this version is different from the original reference

LODTailor is **not a copy-paste distribution of `hp_to_lp_bake.py`**.

The Blender-side processing approach was developed from the ideas/workflow of the MIT-licensed reference below and then substantially adapted into a ComfyUI mesh-processing node.

LODTailor adds its own:

- ComfyUI `MESH` input/output handling
- Mesh extraction and conversion logic
- GLB/OBJ/PLY interoperability
- Large-mesh guard reduction
- Multi-pass target-driven decimation
- Optional voxel rebuild
- Adaptive input-side sealing
- End-of-pipeline Centroid Merge sealing
- Flat-shading and custom-normal handling
- Vertex color and UV reconstruction
- Blender timeout handling
- Automatic temporary-directory cleanup

> **The reference provided a useful starting point; LODTailor was reworked into a dedicated ComfyUI LOD/decimation pipeline with its own conversion, compatibility, performance, sealing, shading, and output logic.**

---

## Third-party reference

The Blender-side high-to-low processing workflow was adapted from:

- [`hp_to_lp_bake.py`](https://github.com/mdj128/aeon-unity-tools/blob/main/hp_to_lp_bake.py)
- Repository: [`mdj128/aeon-unity-tools`](https://github.com/mdj128/aeon-unity-tools)
- Author: Martin Johnson
- Upstream commit audited: `444ff5bf35be1bcf31986fb08dd9b4a5532c84a1`
- License: **MIT**

The applicable upstream license notice is preserved in:

```text
licenses/AEON-UNITY-TOOLS-MIT.txt
```

See the repository's third-party notices for additional licensing information.

---

## License

LODTailor is licensed under:

**GNU General Public License v3.0 or later (GPL-3.0-or-later)**

See [`LICENSE`](LICENSE) for the full license text.

GPL-3.0-or-later permits commercial use, modification, redistribution, and sale, subject to the applicable GPL requirements.

---

## Third-party software

| Component | Role | License / status |
|---|---|---|
| ComfyUI | Host application | External dependency; GPL-3.0 |
| Blender | Background mesh-processing worker | External application; install separately |
| NumPy | Array conversion | BSD-style license |
| trimesh | Mesh loading/conversion | MIT License |

See [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) and [`licenses/`](licenses/) for the repository's applicable notices.

---

## In one sentence

**LODTailor takes large ComfyUI 3D meshes, runs them through a headless Blender decimation pipeline with optional voxel rebuilding and final Centroid Merge sealing, then returns a trimmed, flat-shaded `MESH` for the next stage of your workflow.**

---

## Repository

https://github.com/Mstafa-awad/LODTailor-The-Mesh-Trimmer-ComfyuiNode
