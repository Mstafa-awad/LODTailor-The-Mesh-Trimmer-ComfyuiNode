import copy
import importlib
import inspect
import shutil
import subprocess
import tempfile
import types
from pathlib import Path

import numpy as np


SCRIPT_PATH = Path(__file__).resolve().parent / "decimate_only.py"

PATH_KEYS = (
    "mesh_path",
    "path",
    "filepath",
    "file_path",
    "model_path",
    "glb_path",
    "obj_path",
    "file",
    "src",
)

VERTEX_KEYS = (
    "vertices",
    "verts",
    "positions",
    "points",
    "vertex_positions",
)

FACE_KEYS = (
    "faces",
    "tris",
    "triangles",
    "indices",
    "face_indices",
    "primitive_indices",
)

UV_KEYS = (
    "uvs",
    "uv",
    "vertex_uvs",
    "texture_coords",
)

COLOR_KEYS = (
    "vertex_colors",
    "colors",
    "color",
    "vertex_color",
)

_OFFICIAL_MESH_CLASS = None


def _get_first(data, keys):
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
    else:
        for key in keys:
            value = getattr(data, key, None)
            if value is not None and not callable(value):
                return value

    return None


def _to_numpy_array(value):
    if value is None:
        return None

    if hasattr(value, "detach"):
        try:
            value = value.detach().cpu()
        except Exception:
            pass

    if hasattr(value, "numpy"):
        try:
            return value.numpy()
        except Exception:
            pass

    return np.asarray(value)


def _squeeze_batch_array(value):
    arr = _to_numpy_array(value)

    if arr is None:
        return None

    if arr.ndim == 3 and arr.shape[0] >= 1:
        arr = arr[0]

    return arr


def _resolve_input_path(raw_input):
    raw_input = (raw_input or "").strip()

    if not raw_input:
        return None

    path = Path(raw_input).expanduser()
    candidates = []

    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(Path.cwd() / path)

        try:
            import folder_paths
            candidates.append(Path(folder_paths.get_input_directory()) / path)
        except Exception:
            pass

        try:
            import folder_paths
            candidates.append(Path(folder_paths.get_output_directory()) / path)
        except Exception:
            pass

    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate.resolve()
        except Exception:
            pass

    return path.resolve()


def _extract_existing_path(data):
    value = _get_first(data, PATH_KEYS)

    if value is None:
        return None

    if isinstance(value, (str, Path)):
        resolved = _resolve_input_path(str(value))
        if resolved is not None and resolved.exists():
            return resolved

    return None


def _estimate_vertex_count(vertices):
    try:
        if hasattr(vertices, "ndim"):
            if vertices.ndim == 2:
                return int(vertices.shape[0])
            return int(len(vertices) // 3)

        first = vertices[0]

        if hasattr(first, "__len__") and not isinstance(first, (str, bytes)):
            return len(vertices)

        return len(vertices) // 3
    except Exception:
        return None


def _iter_vertices(vertices):
    try:
        if hasattr(vertices, "ndim"):
            if vertices.ndim == 1:
                flat = list(vertices)
                for i in range(0, len(flat) - 2, 3):
                    yield flat[i:i + 3]
            else:
                for vertex in vertices:
                    yield vertex
            return

        first = vertices[0]

        if hasattr(first, "__len__") and not isinstance(first, (str, bytes)):
            for vertex in vertices:
                yield vertex
        else:
            flat = list(vertices)
            for i in range(0, len(flat) - 2, 3):
                yield flat[i:i + 3]
    except Exception:
        return


def _iter_faces(faces):
    try:
        if hasattr(faces, "ndim"):
            if faces.ndim == 1:
                flat = list(faces)
                for i in range(0, len(flat) - 2, 3):
                    yield flat[i:i + 3]
            else:
                for face in faces:
                    yield face
            return

        first = faces[0]

        if hasattr(first, "__len__") and not isinstance(first, (str, bytes)):
            for face in faces:
                yield face
        else:
            flat = list(faces)
            for i in range(0, len(flat) - 2, 3):
                yield flat[i:i + 3]
    except Exception:
        return


def _try_export_arrays_with_trimesh(vertices, faces, temp_dir, uvs=None, colors=None):
    try:
        import trimesh

        vertex_array = _squeeze_batch_array(vertices)
        face_array = _squeeze_batch_array(faces)

        if vertex_array is None or face_array is None:
            return None

        if vertex_array.ndim == 1:
            vertex_array = vertex_array.reshape(-1, 3)

        if face_array.ndim == 1:
            face_array = face_array.reshape(-1, 3)

        vertex_array = vertex_array.astype(np.float32, copy=False)
        face_array = face_array.astype(np.int64, copy=False)

        mesh = trimesh.Trimesh(
            vertices=vertex_array,
            faces=face_array,
            process=False,
        )

        color_array = _squeeze_batch_array(colors)
        uv_array = _squeeze_batch_array(uvs)

        if color_array is not None:
            if color_array.ndim == 2 and color_array.shape[0] == vertex_array.shape[0]:
                if color_array.dtype.kind == "f":
                    color_array = (np.clip(color_array, 0.0, 1.0) * 255.0).astype(np.uint8)
                else:
                    color_array = color_array.astype(np.uint8)

                if color_array.shape[1] == 3:
                    alpha = np.full((color_array.shape[0], 1), 255, dtype=np.uint8)
                    color_array = np.concatenate([color_array, alpha], axis=1)

                if color_array.shape[1] == 4:
                    try:
                        mesh.visual.vertex_colors = color_array
                    except Exception:
                        pass

        elif uv_array is not None:
            if uv_array.ndim == 2 and uv_array.shape[0] == vertex_array.shape[0]:
                try:
                    mesh.visual = trimesh.visual.TextureVisuals(uv=uv_array.astype(np.float32))
                except Exception:
                    pass

        output_path = temp_dir / "mesh_input.glb"
        mesh.export(str(output_path))

        return output_path

    except Exception:
        return None


def _write_obj_from_arrays(vertices, faces, output_path):
    vertices = _squeeze_batch_array(vertices)
    faces = _squeeze_batch_array(faces)

    if vertices is None or faces is None:
        return

    if vertices.ndim == 1:
        vertices = vertices.reshape(-1, 3)

    if faces.ndim == 1:
        faces = faces.reshape(-1, 3)

    vertex_count = _estimate_vertex_count(vertices)

    with open(output_path, "w", encoding="utf-8") as obj_file:
        for vertex in _iter_vertices(vertices):
            try:
                x, y, z = float(vertex[0]), float(vertex[1]), float(vertex[2])
                obj_file.write(f"v {x} {y} {z}\n")
            except Exception:
                continue

        for face in _iter_faces(faces):
            try:
                face_indices = [int(index) for index in face]
            except Exception:
                continue

            if len(face_indices) < 3:
                continue

            if vertex_count is not None:
                if min(face_indices) >= 1 and max(face_indices) == vertex_count:
                    face_indices = [index - 1 for index in face_indices]

            if vertex_count is not None:
                if any(index < 0 or index >= vertex_count for index in face_indices):
                    continue

            obj_indices = " ".join(str(index + 1) for index in face_indices)
            obj_file.write(f"f {obj_indices}\n")


def _mesh_to_temp_path(mesh_data, temp_dir, seen=None):
    if seen is None:
        seen = set()

    if id(mesh_data) in seen:
        raise ValueError("Recursive mesh input detected")

    seen.add(id(mesh_data))

    if mesh_data is None:
        raise ValueError("MESH input is empty")

    if isinstance(mesh_data, (str, Path)):
        resolved = _resolve_input_path(str(mesh_data))
        if resolved is not None and resolved.exists():
            return resolved
        raise ValueError(f"MESH input path does not exist: {mesh_data}")

    if isinstance(mesh_data, bytes):
        suffix = ".glb"
        if not mesh_data.startswith(b"glTF"):
            suffix = ".bin"

        temp_path = temp_dir / f"mesh_input{suffix}"
        temp_path.write_bytes(mesh_data)
        return temp_path

    if isinstance(mesh_data, (list, tuple)):
        if len(mesh_data) >= 2:
            possible_vertices = mesh_data[0]
            possible_faces = mesh_data[1]

            trimesh_path = _try_export_arrays_with_trimesh(
                possible_vertices,
                possible_faces,
                temp_dir,
            )

            if trimesh_path is not None:
                return trimesh_path

            obj_path = temp_dir / "mesh_input.obj"

            try:
                _write_obj_from_arrays(possible_vertices, possible_faces, obj_path)
                if obj_path.exists() and obj_path.stat().st_size > 0:
                    return obj_path
            except Exception:
                pass

        for item in mesh_data:
            try:
                return _mesh_to_temp_path(item, temp_dir, seen)
            except Exception:
                continue

    existing_path = _extract_existing_path(mesh_data)
    if existing_path is not None:
        return existing_path

    if isinstance(mesh_data, dict):
        for key in ("mesh", "data", "model", "object", "scene", "result", "item"):
            if key in mesh_data and mesh_data[key] is not None:
                try:
                    return _mesh_to_temp_path(mesh_data[key], temp_dir, seen)
                except Exception:
                    pass

        if "bytes" in mesh_data and mesh_data["bytes"] is not None:
            try:
                return _mesh_to_temp_path(mesh_data["bytes"], temp_dir, seen)
            except Exception:
                pass

    else:
        for attr in ("mesh", "data", "model", "object", "scene"):
            if hasattr(mesh_data, attr):
                try:
                    return _mesh_to_temp_path(getattr(mesh_data, attr), temp_dir, seen)
                except Exception:
                    pass

        for method_name in ("to_dict", "as_dict", "get_dict"):
            if hasattr(mesh_data, method_name):
                try:
                    method = getattr(mesh_data, method_name)
                    if callable(method):
                        return _mesh_to_temp_path(method(), temp_dir, seen)
                except Exception:
                    pass

    vertices = _get_first(mesh_data, VERTEX_KEYS)
    faces = _get_first(mesh_data, FACE_KEYS)

    if vertices is not None and faces is not None:
        uvs = _get_first(mesh_data, UV_KEYS)
        colors = _get_first(mesh_data, COLOR_KEYS)

        trimesh_path = _try_export_arrays_with_trimesh(
            vertices,
            faces,
            temp_dir,
            uvs=uvs,
            colors=colors,
        )

        if trimesh_path is not None:
            return trimesh_path

        obj_path = temp_dir / "mesh_input.obj"
        _write_obj_from_arrays(vertices, faces, obj_path)

        if obj_path.exists() and obj_path.stat().st_size > 0:
            return obj_path

    if hasattr(mesh_data, "export"):
        for suffix in (".glb", ".obj"):
            export_path = temp_dir / f"mesh_input{suffix}"
            try:
                mesh_data.export(str(export_path))
                if export_path.exists() and export_path.stat().st_size > 0:
                    return export_path
            except Exception:
                pass

    if hasattr(mesh_data, "write"):
        export_path = temp_dir / "mesh_input.obj"
        try:
            mesh_data.write(str(export_path))
            if export_path.exists() and export_path.stat().st_size > 0:
                return export_path
        except Exception:
            pass

    raise ValueError(
        "Could not extract a usable mesh from the MESH input.\n"
        "Supported inputs: official ComfyUI mesh object, mesh file path, GLB bytes, "
        "trimesh-like object, or dict/object with vertices + faces."
    )


def _load_processed_arrays(processed_path):
    import trimesh

    loaded = trimesh.load(str(processed_path), force="mesh")

    # Undo glTF vertex splits (position-only weld, like manual Merge by Distance).
    try:
        loaded.merge_vertices(merge_tex=True, merge_norm=True)
    except Exception:
        pass

    try:
        print(
            f"[LODsmith] OUTPUT CHECK watertight={loaded.is_watertight} "
            f"winding_consistent={loaded.is_winding_consistent} "
            f"bodies={loaded.body_count} euler={loaded.euler_number}",
            flush=True,
        )
    except Exception:
        pass

    vertices = np.asarray(loaded.vertices, dtype=np.float32)
    faces = np.asarray(loaded.faces, dtype=np.int64)

    # IMPORTANT: do NOT bake trimesh's smooth vertex normals into the output.
    # Smooth normals here are what made the model look shade-smooth everywhere.
    normals = None

    uvs = None
    try:
        if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
            possible_uvs = np.asarray(loaded.visual.uv, dtype=np.float32)
            if possible_uvs.shape[0] == vertices.shape[0]:
                uvs = possible_uvs
    except Exception:
        pass

    colors = None
    try:
        if getattr(loaded.visual, "kind", None) == "vertex":
            vertex_colors = getattr(loaded.visual, "vertex_colors", None)
            if vertex_colors is not None:
                colors = np.asarray(vertex_colors)

                if colors.dtype == np.uint8:
                    colors = colors.astype(np.float32) / 255.0
                else:
                    colors = colors.astype(np.float32)

                if colors.shape[0] != vertices.shape[0]:
                    colors = None
    except Exception:
        pass

    return vertices, faces, normals, uvs, colors


def _is_official_mesh_item(obj):
    if obj is None:
        return False

    if isinstance(obj, (str, Path, bytes, dict, list, tuple, set)):
        return False

    return (
        hasattr(obj, "vertices")
        and hasattr(obj, "faces")
        and hasattr(obj, "vertex_colors")
    )


def _extract_official_item(mesh_data, depth=0):
    if depth > 4 or mesh_data is None:
        return None

    if _is_official_mesh_item(mesh_data):
        return mesh_data

    if isinstance(mesh_data, dict):
        for key in ("mesh", "data", "model", "object", "item", "result"):
            if key in mesh_data:
                found = _extract_official_item(mesh_data[key], depth + 1)
                if found is not None:
                    return found

    if isinstance(mesh_data, (list, tuple)):
        for item in mesh_data:
            found = _extract_official_item(item, depth + 1)
            if found is not None:
                return found

    if hasattr(mesh_data, "mesh"):
        found = _extract_official_item(getattr(mesh_data, "mesh"), depth + 1)
        if found is not None:
            return found

    return None


def _public_attrs(obj):
    attrs = {}

    if isinstance(obj, dict):
        attrs.update(obj)
        return attrs

    if hasattr(obj, "__dict__"):
        for key, value in vars(obj).items():
            if not key.startswith("_"):
                attrs[key] = value

    if not attrs:
        for key in dir(obj):
            if key.startswith("_"):
                continue

            try:
                value = getattr(obj, key)
            except Exception:
                continue

            if callable(value):
                continue

            attrs[key] = value

    return attrs


def _find_official_mesh_class():
    global _OFFICIAL_MESH_CLASS

    if _OFFICIAL_MESH_CLASS is False:
        return None

    if _OFFICIAL_MESH_CLASS is not None:
        return _OFFICIAL_MESH_CLASS

    module_names = (
        "comfy_api.latest._io",
        "comfy_extras.nodes_save_3d",
        "comfy_extras.nodes_3d",
        "comfy.mesh",
    )

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)

            for _, cls in inspect.getmembers(module, inspect.isclass):
                annotations = getattr(cls, "__annotations__", {})

                if "vertex_colors" in annotations and "vertices" in annotations:
                    _OFFICIAL_MESH_CLASS = cls
                    return cls

        except Exception:
            pass

    _OFFICIAL_MESH_CLASS = False
    return None


def _try_construct_official_mesh(updates):
    cls = _find_official_mesh_class()

    if cls is None:
        return None

    try:
        import dataclasses

        if dataclasses.is_dataclass(cls):
            field_names = {field.name for field in dataclasses.fields(cls)}
            kwargs = {
                key: value
                for key, value in updates.items()
                if key in field_names
            }
            return cls(**kwargs)
    except Exception:
        pass

    try:
        return cls(**updates)
    except Exception:
        pass

    try:
        obj = cls()
        for key, value in updates.items():
            setattr(obj, key, value)
        return obj
    except Exception:
        return None


def _convert_geometry_array(arr, original_attr, kind):
    if arr is None:
        return None

    arr = np.asarray(arr)

    if kind == "faces":
        arr = arr.astype(np.int64, copy=False)
    else:
        arr = arr.astype(np.float32, copy=False)

    want_batch = True

    if original_attr is not None:
        shape = getattr(original_attr, "shape", None)

        if shape is not None:
            if len(shape) == arr.ndim + 1:
                want_batch = True
            elif len(shape) == arr.ndim:
                want_batch = False
            else:
                want_batch = True
        else:
            want_batch = True

    if want_batch:
        if arr.ndim == 2:
            arr = arr[None, ...]
    else:
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]

    if original_attr is not None:
        if (
            hasattr(original_attr, "dtype")
            and hasattr(original_attr, "device")
            and hasattr(original_attr, "numpy")
        ):
            try:
                import torch
                tensor = torch.from_numpy(np.ascontiguousarray(arr))
                return tensor.to(dtype=original_attr.dtype, device=original_attr.device)
            except Exception:
                return arr

        if isinstance(original_attr, np.ndarray):
            return arr.astype(original_attr.dtype, copy=False)

    try:
        import torch
        return torch.from_numpy(np.ascontiguousarray(arr))
    except Exception:
        return arr


def _prepare_color_array(colors, vertex_count, template_color_attr):
    desired_channels = 3

    if template_color_attr is not None:
        shape = getattr(template_color_attr, "shape", None)

        if shape is not None and len(shape) > 0:
            if shape[-1] in (3, 4):
                desired_channels = int(shape[-1])

    if colors is None:
        return np.ones((vertex_count, desired_channels), dtype=np.float32)

    colors = np.asarray(colors, dtype=np.float32)

    if colors.ndim == 3:
        colors = colors[0]

    if colors.ndim == 1:
        if colors.size == vertex_count * 3:
            colors = colors.reshape(vertex_count, 3)
        elif colors.size == vertex_count * 4:
            colors = colors.reshape(vertex_count, 4)
        else:
            return np.ones((vertex_count, desired_channels), dtype=np.float32)

    if colors.shape[0] != vertex_count:
        return np.ones((vertex_count, desired_channels), dtype=np.float32)

    if desired_channels == 3 and colors.shape[1] == 4:
        colors = colors[:, :3]

    if desired_channels == 4 and colors.shape[1] == 3:
        alpha = np.ones((vertex_count, 1), dtype=np.float32)
        colors = np.concatenate([colors, alpha], axis=1)

    if colors.shape[1] not in (3, 4):
        colors = colors[:, :3]

    return colors.astype(np.float32, copy=False)


def _make_output_mesh(original_mesh, processed_path):
    vertices, faces, normals, uvs, colors = _load_processed_arrays(processed_path)

    template = _extract_official_item(original_mesh)

    template_vertices = getattr(template, "vertices", None) if template is not None else None
    template_faces = getattr(template, "faces", None) if template is not None else None
    template_colors = getattr(template, "vertex_colors", None) if template is not None else None
    template_uvs = getattr(template, "uvs", None) if template is not None else None
    template_normals = getattr(template, "normals", None) if template is not None else None

    colors = _prepare_color_array(colors, vertices.shape[0], template_colors)

    updates = {
        "vertices": _convert_geometry_array(vertices, template_vertices, "vertices"),
        "faces": _convert_geometry_array(faces, template_faces, "faces"),
        "vertex_colors": _convert_geometry_array(colors, template_colors, "colors"),
        "uvs": _convert_geometry_array(uvs, template_uvs, "uvs") if uvs is not None else None,
        "normals": None,
    }

    if template is not None and hasattr(template, "vertex_normals"):
        updates["vertex_normals"] = None

    if template is not None and hasattr(template, "vertex_uvs"):
        updates["vertex_uvs"] = updates["uvs"]

    if template is not None:
        try:
            output_mesh = copy.copy(template)

            for key, value in updates.items():
                if hasattr(template, key) or key in (
                    "vertices",
                    "faces",
                    "vertex_colors",
                    "uvs",
                    "normals",
                    "vertex_normals",
                    "vertex_uvs",
                ):
                    setattr(output_mesh, key, value)

            return output_mesh

        except Exception:
            pass

        base_attrs = _public_attrs(template)
        base_attrs.update(updates)

        constructed = _try_construct_official_mesh(base_attrs)

        if constructed is not None:
            return constructed

        return types.SimpleNamespace(**base_attrs)

    constructed = _try_construct_official_mesh(updates)

    if constructed is not None:
        return constructed

    return types.SimpleNamespace(**updates)


class LODTailorTheMeshTrimmer:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mesh": ("MESH",),
                "blender_path": ("STRING", {
                    "default": "blender",
                }),
                "target_tris": ("INT", {
                    "default": 60000,
                    "min": 1,
                    "max": 10_000_000,
                    "step": 1,
                }),
                "passes": ("INT", {
                    "default": 3,
                    "min": 1,
                    "max": 1000,
                    "step": 1,
                }),
                "tolerance": ("FLOAT", {
                    "default": 1.05,
                    "min": 1.0,
                    "max": 2.0,
                    "step": 0.001,
                }),
                "intermediate_ratio": ("FLOAT", {
                    "default": 0.50,
                    "min": 0.001,
                    "max": 1.0,
                    "step": 0.001,
                }),
                "last_ratio": ("FLOAT", {
                    "default": 0.25,
                    "min": 0.001,
                    "max": 1.0,
                    "step": 0.001,
                }),
                "final_ratio": ("FLOAT", {
                    "default": 0.20,
                    "min": 0.001,
                    "max": 1.0,
                    "step": 0.001,
                }),
                "triangulate": ("BOOLEAN", {
                    "default": True,
                }),
                "symmetry": ("BOOLEAN", {
                    "default": False,
                }),
                "voxel_rebuild": ("BOOLEAN", {
                    "default": True,
                }),
                "relative_voxel_size": ("FLOAT", {
                    "default": 0.0015,
                    "min": 0.00001,
                    "max": 0.1,
                    "step": 0.00001,
                }),
                "minimum_voxel_size": ("FLOAT", {
                    "default": 0.000001,
                    "min": 0.000001,
                    "max": 1.0,
                    "step": 0.000001,
                }),
                "seal_distance": ("FLOAT", {
                    "default": 0.0001,
                    "min": 0.000001,
                    "max": 0.1,
                    "step": 0.000001,
                }),
                "seal_max_steps": ("INT", {
                    "default": 100,
                    "min": 1,
                    "max": 1000,
                    "step": 1,
                }),
                "seal_keep_trying": ("BOOLEAN", {
                    "default": True,
                }),
                "timeout_seconds": ("INT", {
                    "default": 1800,
                    "min": 0,
                    "max": 86400,
                    "step": 1,
                }),
            }
        }

    RETURN_TYPES = ("MESH",)
    RETURN_NAMES = ("mesh",)
    FUNCTION = "run"
    CATEGORY = "LODsmith"
    OUTPUT_NODE = True

    def run(
        self,
        mesh,
        blender_path,
        target_tris,
        passes,
        tolerance,
        intermediate_ratio,
        last_ratio,
        final_ratio,
        triangulate,
        symmetry,
        voxel_rebuild,
        relative_voxel_size,
        minimum_voxel_size,
        seal_distance,
        seal_max_steps,
        seal_keep_trying,
        timeout_seconds,
    ):
        temp_dir = Path(tempfile.mkdtemp(prefix="lodsmith_decimator_"))

        try:
            if not SCRIPT_PATH.exists():
                raise ValueError(
                    f"Missing decimate_only.py here:\n{SCRIPT_PATH}\n\n"
                    "Put the exact working Blender script next to this __init__.py file."
                )

            input_path = _mesh_to_temp_path(mesh, temp_dir)
            processed_path = temp_dir / "lodsmith_decimated.glb"

            cli_args = [
                "--input", str(input_path),
                "--output", str(processed_path),
                "--tris", str(int(target_tris)),
                "--passes", str(int(passes)),
                "--tolerance", str(float(tolerance)),
                "--intermediate-ratio", str(float(intermediate_ratio)),
                "--last-ratio", str(float(last_ratio)),
                "--final-ratio", str(float(final_ratio)),
                "--relative-voxel-size", str(float(relative_voxel_size)),
                "--minimum-voxel-size", str(float(minimum_voxel_size)),
                "--seal-distance", str(float(seal_distance)),
                "--seal-max-steps", str(int(seal_max_steps)),
            ]

            if triangulate:
                cli_args.append("--triangulate")

            if symmetry:
                cli_args.append("--symmetry")

            if voxel_rebuild:
                cli_args.append("--voxel")

            if seal_keep_trying:
                cli_args.append("--seal-keep-trying")

            blender_executable = (blender_path or "").strip() or "blender"

            command = [
                blender_executable,
                "--background",
                "--python",
                str(SCRIPT_PATH),
                "--",
            ] + cli_args

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            try:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creation_flags,
                    timeout=(int(timeout_seconds) if int(timeout_seconds) > 0 else None),
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"Blender decimation timed out after {int(timeout_seconds)}s "
                    "(raise timeout_seconds or lower target detail)."
                )

            if process.returncode != 0 or not processed_path.exists():
                print("[LODsmith Decimator] Blender failed.")
                print(process.stdout or "")
                print(process.stderr or "")
                raise RuntimeError(
                    "LODsmith decimation failed. Check the ComfyUI console for the Blender log."
                )

            output_mesh = _make_output_mesh(mesh, processed_path)

            return (output_mesh,)

        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


NODE_CLASS_MAPPINGS = {
    "LODTailorTheMeshTrimmer": LODTailorTheMeshTrimmer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LODTailorTheMeshTrimmer": "LODTailor The Mesh Trimmer",
}