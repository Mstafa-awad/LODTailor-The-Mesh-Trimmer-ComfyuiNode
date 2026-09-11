# LODTailor — The Mesh Trimmer

High-performance, headless Blender mesh decimation and LOD (Level of Detail) optimization custom node for **ComfyUI**. Built specifically to handle ultra-dense AI-generated 3D meshes rapidly without stalling system memory or UI execution.

---

## Features

* **C-Level Modifier Stack:** Leverages Blender's native C-level object modifiers (`WELD`, `DECIMATE`, `REMESH`) in headless mode, replacing slow Python edit-mode iterations with high-speed parallel reduction.
* **Smart Multi-Stage Reduction:** Includes an automated bulk-crush stage for massive meshes (3M+ triangles) to drastically lower polycounts before fine decimation, eliminating memory bottlenecks.
* **Universal Mesh Input Handling:** Automatically extracts and converts standard ComfyUI `MESH` objects, PyTorch tensors, Trimesh instances, raw GLB/OBJ byte buffers, dicts, and file paths.
* **Attribute Preservation:** Retains critical mesh data through processing, including vertex colors, UV coordinates, and surface normals.
* **Optional Voxel & Surface Cleanup:** Integrated toggleable controls for voxel rebuilds, merge-by-distance welding, planar limited dissolve, and shell debris removal.
* **Isolated Background Worker:** Launches Blender asynchronously in `--background` mode, preventing ComfyUI interface lockups or crash cascades.

---

## Requirements

1. **ComfyUI**
2. **Blender (2.8+ / 3.x / 4.x):** Must be installed on your system.
   * If `blender` is in your system `PATH`, no further configuration is needed.
   * If Blender is installed in a custom location, provide the full path to the executable in the `blender_path` node input.

---

## Installation

1. Open a terminal/command prompt and navigate to your ComfyUI `custom_nodes` folder:
   ```bash
   cd ComfyUI/custom_nodes/
   ```

2. Clone this repository:
   ```bash
   git clone https://github.com/Mstafa-awad/LODTailor-The-Mesh-Trimmer-ComfyuiNode.git
   ```

3. Restart ComfyUI. The node will be available under the **LODsmith** category as **LODTailor The Mesh Trimmer**.

---

## Node Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `mesh` | **MESH** | — | Input mesh object (ComfyUI Mesh, path, dict, or tensor). |
| `blender_path` | **STRING** | `blender` | Path to the Blender executable or `blender` if alias is set. |
| `target_tris` | **INT** | `100` | Target triangle count for the final decimated output mesh. |
| `voxel_rebuild` | **BOOLEAN** | `True` | Fuses messy or overlapping geometry into a unified volume via voxel remeshing. |
| `relative_voxel_size` | **FLOAT** | `0.0015` | Voxel size scaled relative to the object's maximum bound dimension. |
| `merge_by_distance` | **BOOLEAN** | `True` | Welds duplicate or closely overlapping vertices prior to decimation. |
| `merge_distance` | **FLOAT** | `0.0001` | Distance threshold for vertex welding. |
| `limited_dissolve` | **BOOLEAN** | `False` | Merges coplanar faces based on the angle threshold. |
| `dissolve_angle` | **FLOAT** | `5.0` | Angle limit (in degrees) for planar face reduction. |
| `cleanup_shells` | **BOOLEAN** | `True` | Automatically drops tiny disconnected mesh fragments/debris. |
| `min_shell_faces` | **INT** | `500` | Minimum face count required to keep a disconnected mesh shell. |
| `triangulate` | **BOOLEAN** | `True` | Ensures all output faces are converted to triangles. |
| `symmetry` | **BOOLEAN** | `False` | Enforces symmetrical decimation across the mesh axis. |
| `apply_transforms` | **BOOLEAN** | `True` | Bakes object location, rotation, and scale prior to modifier execution. |
| `join_meshes` | **BOOLEAN** | `True` | Joins multi-part meshes into a single object before processing. |

---

## Outputs

* **mesh (`MESH`):** The processed, decimated ComfyUI-native mesh containing updated geometry data, vertex colors, UVs, and normal vectors.

---

## Credits

* Blender-side high-to-low mesh processing workflow adapted from original work by Martin Johnson (`hp_to_lp_bake.py` / `aeon-unity-tools`, MIT License).

---

## License

This project is licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**. See `LICENSE` for details.

---

## 🚀 SUPPORT MOSTAADTECH

### ❤️ Enjoying this project / workflow?

I’m **MostAadTech**, I create FREE ComfyUI workflows, local AI tools, 3D pipelines, and open-source projects.

If this project or workflow helped you, **please consider following me or supporting my work**. It helps me keep building, testing, and releasing more free tools and workflows.

---

## 💜 Support Me on Patreon

👉 **[Support MostAadTech on Patreon](https://www.patreon.com/cw/MostafaAwad/membership)**

Your support helps me spend more time developing **FREE AI tools, ComfyUI workflows, and 3D pipelines**.

---

## 🌐 Follow MostAadTech

* ▶️ **[YouTube](https://www.youtube.com/@MostAadTech)** — Tutorials, workflows & AI projects
* 📸 **[Instagram](https://www.instagram.com/mostaadtech/)** — Projects, updates & behind the scenes
* 𝕏 **[X / Twitter](https://x.com/MostAadTech)** — Updates, releases & experiments
* 💻 **[GitHub](https://github.com/Mstafa-awad)** — Open-source projects & code

---

### ⭐ One Follow Helps

**Follow • Star • Share • Support**

Every follow, GitHub star, share, and Patreon supporter helps me continue making **FREE tools for the AI community.**

**Thank you for supporting MostAadTech! ❤️**
