# LODTailor — The Mesh Trimmer

A ComfyUI mesh optimization and LOD utility that sends mesh processing to Blender as an external worker.

LODTailor is designed for **fast, practical high-poly → low-poly mesh reduction** inside a ComfyUI workflow, especially when working with generated 3D assets.

## What LODTailor does

LODTailor takes a ComfyUI `MESH` object, converts it into a temporary mesh file when necessary, processes it through Blender in background mode, and returns the result as a ComfyUI-compatible `MESH` object.

The main workflow is:

1. Accept a ComfyUI `MESH` or compatible mesh-like input.
2. Convert different mesh representations into a temporary GLB/OBJ when needed.
3. Run Blender headlessly so Blender does not need to open a visible UI.
4. Apply fast C-level Blender modifiers for welding, planar reduction, voxel rebuilds, and decimation.
5. Use a bulk reduction stage on very large meshes before the final target reduction to avoid excessive memory/time costs.
6. Export the processed mesh and rebuild a ComfyUI-style `MESH` result.
7. Preserve available geometry data such as vertex colors, UVs, and normals where supported by the input/output format.

## Why this version is different from the original reference

LODTailor is **not a copy-paste distribution of `hp_to_lp_bake.py`**.

The Blender-side processing was developed from the ideas/workflow of the MIT-licensed reference listed below, then substantially adapted and extended to work as a ComfyUI mesh-processing node.

The original reference had limitations for the workflow I needed, so LODTailor was reworked to focus on **speed, large generated meshes, ComfyUI compatibility, and reliable mesh conversion**.

### Main improvements in LODTailor

- **ComfyUI-native input/output:** accepts the ComfyUI `MESH` type instead of being a standalone baking script.
- **Flexible mesh input handling:** supports mesh paths, GLB bytes, arrays, tuples, dictionaries, and mesh-like objects.
- **Automatic mesh extraction:** searches common mesh/geometry fields and can fall back to temporary GLB/OBJ conversion.
- **ComfyUI mesh reconstruction:** converts Blender's processed result back into the mesh structure expected by ComfyUI 3D nodes.
- **Attribute handling:** preserves or reconstructs vertex colors and can carry UVs and normals when available.
- **Fast Blender modifier pipeline:** uses Blender's Object-Mode/C-level modifiers instead of relying on slow manual Edit-Mode operations for the main reduction stages.
- **Large-mesh protection:** very large meshes can be reduced to an intermediate size before the final target reduction, helping prevent memory-heavy processing from becoming unnecessarily slow.
- **Optional voxel rebuild:** supports Blender voxel remeshing as part of the processing pipeline when enabled.
- **Optional cleanup controls:** exposes settings for welding, loose geometry removal, shell cleanup flags, normal recalculation, limited dissolve, and other processing controls.
- **Headless/background execution:** Blender is launched as an external background worker, keeping the ComfyUI workflow interface responsive.
- **Automatic temporary-file cleanup:** temporary conversion/processing files are removed after the operation finishes.

In simple terms: **the reference provided a useful starting point, while LODTailor was reworked into a dedicated ComfyUI LOD/decimation pipeline with additional conversion, compatibility, performance, and mesh-handling logic.**

## Third-party reference

The Blender-side high-to-low processing approach was adapted from:

- `hp_to_lp_bake.py` in [mdj128/aeon-unity-tools](https://github.com/mdj128/aeon-unity-tools/blob/main/hp_to_lp_bake.py)
- Author: Martin Johnson
- Upstream commit audited: `444ff5bf35be1bcf31986fb08dd9b4a5532c84a1`
- License: **MIT**

The complete upstream MIT license notice is preserved in:

`licenses/AEON-UNITY-TOOLS-MIT.txt`

This attribution is kept because the referenced source is MIT licensed.

## License

LODTailor is licensed under the **GNU General Public License v3 or later (GPL-3.0-or-later)**.

See `LICENSE` for the full license text.

GPL-3.0-or-later permits commercial use, modification, redistribution, and sale, provided the applicable GPL requirements are followed when distributing the software.

## Runtime dependencies and licensing

LODTailor does not bundle Blender, ComfyUI, NumPy, or trimesh.

- **ComfyUI:** external host application; GPL-3.0.
- **Blender:** external application; obtain it separately from [blender.org](https://www.blender.org/).
- **NumPy:** provided by the ComfyUI/Python environment; BSD-style license.
- **trimesh:** imported at runtime for mesh conversion/loading; MIT License.

The relevant notices/licenses are included in `THIRD-PARTY-NOTICES.md` and the `licenses/` directory.

## Installation

Copy the folder into:

```text
ComfyUI/custom_nodes/LODTailor-The-Mesh-Trimmer
```

Then configure the Blender executable/path in the node. The default value is:

```text
blender
```

No additional pip packages are intentionally required by LODTailor beyond what is already available in the ComfyUI environment.

## In one sentence

**LODTailor takes the basic high-to-low mesh processing idea, rebuilds it around ComfyUI, and adds the mesh conversion, compatibility, cleanup, and performance logic needed for practical AI-generated 3D workflows.**
