#!/usr/bin/env python3
"""QuantumForge spglib/seekpath JSON-line sidecar (protocol v2).

Reads one JSON object from stdin and writes one JSON object to stdout.
Never executes arbitrary code.

Ops:
  - get_dataset
  - standardize_primitive
  - standardize_conventional
  - seekpath

Requires: numpy, spglib
Optional for seekpath: seekpath
"""
from __future__ import annotations

import json
import sys


PROTOCOL = "2"


def _get(dataset, name, default=None):
    if isinstance(dataset, dict):
        return dataset.get(name, default)
    return getattr(dataset, name, default)


def _cell_from_req(req):
    import numpy as np

    lattice = np.array(req["lattice"], dtype=float)
    positions_cart = np.array(req["positions"], dtype=float)
    numbers = np.array(req["numbers"], dtype=int)
    # Java lattice[i] is vector i as row; convert Cartesian -> fractional.
    frac = positions_cart @ np.linalg.inv(lattice)
    return lattice, frac, numbers


def main() -> int:
    try:
        raw = sys.stdin.readline()
        if not raw:
            print(json.dumps({"error": "empty request"}))
            return 2
        req = json.loads(raw)
        protocol = str(req.get("protocol", ""))
        if protocol not in ("1", "2"):
            print(json.dumps({"error": f"unsupported protocol {protocol}"}))
            return 2
        op = req.get("op", "get_dataset")
        try:
            import numpy as np
            import spglib
        except Exception as exc:  # pragma: no cover
            print(json.dumps({"error": f"spglib/numpy unavailable: {exc}"}))
            return 3

        lattice, frac, numbers = _cell_from_req(req)
        tol = float(req.get("tolerance", 1.0e-5))
        cell = (lattice, frac, numbers)

        if op == "get_dataset":
            dataset = spglib.get_symmetry_dataset(cell, symprec=tol)
            if dataset is None:
                print(json.dumps({"error": "spglib returned no dataset"}))
                return 4
            out = {
                "protocol": PROTOCOL,
                "number": int(_get(dataset, "number", 0)),
                "international": str(
                    _get(dataset, "international", _get(dataset, "international_symbol", ""))
                ),
                "hall": str(_get(dataset, "hall", _get(dataset, "hall_symbol", ""))),
                "spglib_version": getattr(spglib, "__version__", "unknown"),
                "tolerance": tol,
            }
            print(json.dumps(out))
            return 0

        if op in ("standardize_primitive", "standardize_conventional"):
            to_primitive = op == "standardize_primitive"
            std = spglib.standardize_cell(cell, to_primitive=to_primitive, symprec=tol)
            if std is None:
                print(json.dumps({"error": "spglib.standardize_cell returned None"}))
                return 4
            std_lattice, std_pos, std_numbers = std
            dataset = spglib.get_symmetry_dataset((std_lattice, std_pos, std_numbers), symprec=tol)
            out = {
                "protocol": PROTOCOL,
                "op": op,
                "kind": "primitive" if to_primitive else "conventional",
                "lattice": np.asarray(std_lattice, dtype=float).tolist(),
                "positions": np.asarray(std_pos, dtype=float).tolist(),
                "numbers": [int(x) for x in np.asarray(std_numbers).tolist()],
                "number": int(_get(dataset, "number", 0)) if dataset is not None else 0,
                "international": str(
                    _get(dataset, "international", _get(dataset, "international_symbol", ""))
                )
                if dataset is not None
                else "",
                "spglib_version": getattr(spglib, "__version__", "unknown"),
                "tolerance": tol,
            }
            print(json.dumps(out))
            return 0

        if op == "seekpath":
            try:
                import seekpath
            except Exception as exc:  # pragma: no cover
                print(json.dumps({"error": f"seekpath unavailable: {exc}"}))
                return 3
            # seekpath expects (cell, positions, numbers) with fractional coords.
            structure = (lattice.tolist(), frac.tolist(), [int(x) for x in numbers.tolist()])
            path_data = seekpath.get_path(structure, symprec=tol)
            # Build ordered point list from path segments.
            point_coords = path_data.get("point_coords", {})
            path_segments = path_data.get("path", [])
            ordered = []
            seen = set()
            for a, b in path_segments:
                for label in (a, b):
                    if label in seen:
                        continue
                    seen.add(label)
                    coords = point_coords.get(label, [0.0, 0.0, 0.0])
                    ordered.append([label, [float(coords[0]), float(coords[1]), float(coords[2])]])
            out = {
                "protocol": PROTOCOL,
                "op": "seekpath",
                "path": ordered,
                "number": int(path_data.get("spacegroup_number", 0) or 0),
                "international": str(path_data.get("spacegroup_international", "") or ""),
                "seekpath_version": getattr(seekpath, "__version__", "unknown"),
                "spglib_version": getattr(spglib, "__version__", "unknown"),
                "tolerance": tol,
            }
            print(json.dumps(out))
            return 0

        print(json.dumps({"error": f"unsupported op {op}"}))
        return 2
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
