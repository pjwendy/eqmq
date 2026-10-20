"""Read an EQEmu navmesh (<zone>.nav, as the server loads it) for the map viewer.

The file is "EQNAVMESH", version 2, then a zlib-deflated body: the tile count, Detour's
dtNavMeshParams, and each tile's Detour data. Only the polygons are read (not the detail mesh)
and they're grouped into islands: pieces of the mesh a character can walk between. Detour links
tiles when it loads them, so edges on tile borders are matched up here, as are off-mesh
connections (jumps, ladders, ...).

Coordinates come back in the viewer's map space: (-x, -y) of the game's x and y.
"""
from __future__ import annotations

import os
import struct
import zlib

VERTS_PER_POLY = 6
HEADER = struct.Struct("<15i3f3f3ff")  # dtMeshHeader, 100 bytes
POLY = struct.Struct("<I6H6HHBB")       # dtPoly, 32 bytes
OFFMESH = struct.Struct("<7fHBBI")      # dtOffMeshConnection, 36 bytes
EXT_LINK = 0x8000
POLYTYPE_OFFMESH = 1


def _align4(n: int) -> int:
    return (n + 3) & ~3


class _Islands:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[b] = a


def read_nav(path: str) -> dict:
    """{"polys": [[island, z, mx1, my1, mx2, my2, ...], ...], "links": [[mx1, my1, z1, mx2, my2, z2], ...],
    "islands": n}, islands numbered largest first."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:9] != b"EQNAVMESH" or struct.unpack_from("<I", raw, 9)[0] != 2:
        raise ValueError(f"{path} isn't an EQNAVMESH version 2 file")
    body = zlib.decompress(raw[21:])
    (tiles,) = struct.unpack_from("<I", body, 0)
    off = 4 + 28  # the tile count, then dtNavMeshParams

    polys = []    # (verts [(x, y, z) recast], tile index)
    edges = []    # (poly, tile, a, b): edges on a tile border, to match across tiles
    links = []    # off-mesh connections: (a, b) recast points
    internal = []
    for tile in range(tiles):
        _ref, size = struct.unpack_from("<Ii", body, off)
        off += 8
        data = memoryview(body)[off:off + size]
        off += size
        h = HEADER.unpack_from(data, 0)
        poly_count, vert_count, max_links, detail_meshes, detail_verts, detail_tris, bv_nodes, offmesh_count = h[6:14]
        p = _align4(HEADER.size)
        verts = struct.unpack_from(f"<{vert_count * 3}f", data, p)
        p += _align4(4 * 3 * vert_count)
        first = len(polys)
        tile_polys = [POLY.unpack_from(data, p + i * POLY.size) for i in range(poly_count)]
        p += _align4(POLY.size * poly_count)
        p += _align4(12 * max_links) + _align4(12 * detail_meshes) + _align4(4 * 3 * detail_verts)
        p += _align4(4 * detail_tris) + _align4(16 * bv_nodes)
        for i in range(offmesh_count):
            c = OFFMESH.unpack_from(data, p + i * OFFMESH.size)
            links.append((c[0:3], c[3:6]))
        for i, poly in enumerate(tile_polys):
            n = poly[14]
            pv = [verts[poly[1 + k] * 3:poly[1 + k] * 3 + 3] for k in range(n)]
            ground = (poly[15] >> 6) != POLYTYPE_OFFMESH
            polys.append((pv if ground else [], tile))
            if not ground:
                continue
            for k in range(n):
                nei = poly[7 + k]
                if nei and not nei & EXT_LINK:
                    internal.append((first + i, first + nei - 1))
                elif nei & EXT_LINK:
                    edges.append((first + i, tile, pv[k], pv[(k + 1) % n]))

    isl = _Islands(len(polys))
    for a, b in internal:
        isl.join(a, b)
    # border edges: same line (x or z fixed), overlapping, at about the same height, other tile
    lines: dict = {}
    for e in edges:
        _, _, a, b = e
        if abs(a[0] - b[0]) < 0.01:
            key = ("x", round(a[0], 1))
            lo, hi = sorted((a[2], b[2]))
        elif abs(a[2] - b[2]) < 0.01:
            key = ("z", round(a[2], 1))
            lo, hi = sorted((a[0], b[0]))
        else:
            continue
        lines.setdefault(key, []).append((lo, hi, (a[1] + b[1]) / 2, e))
    for segs in lines.values():
        segs.sort(key=lambda s: s[0])
        for i, (lo, hi, y, e) in enumerate(segs):
            for lo2, hi2, y2, e2 in segs[i + 1:]:
                if lo2 >= hi - 0.01:
                    break
                if e2[1] != e[1] and abs(y2 - y) < 4.0:
                    isl.join(e[0], e2[0])

    def poly_at(pt):
        best, best_d = None, 1e9
        for i, (pv, _) in enumerate(polys):
            if not pv:
                continue
            inside = False
            for k in range(len(pv)):
                (x1, _, z1), (x2, _, z2) = pv[k], pv[k - 1]
                if (z1 > pt[2]) != (z2 > pt[2]) and pt[0] < (x2 - x1) * (pt[2] - z1) / (z2 - z1) + x1:
                    inside = not inside
            if inside:
                d = abs(sum(v[1] for v in pv) / len(pv) - pt[1])
                if d < best_d:
                    best, best_d = i, d
        return best

    for a, b in links:
        pa, pb = poly_at(a), poly_at(b)
        if pa is not None and pb is not None:
            isl.join(pa, pb)

    # number the islands by size, largest first
    area: dict[int, float] = {}
    for i, (pv, _) in enumerate(polys):
        if pv:
            s = sum(pv[k][0] * pv[k - 1][2] - pv[k - 1][0] * pv[k][2] for k in range(len(pv)))
            area[isl.find(i)] = area.get(isl.find(i), 0.0) + abs(s) / 2
    order = {root: n for n, root in enumerate(sorted(area, key=lambda r: -area[r]))}
    out = []
    for i, (pv, _) in enumerate(polys):
        if not pv:
            continue
        row = [order[isl.find(i)], round(sum(v[1] for v in pv) / len(pv), 1)]
        for x, _, z in pv:
            row += [round(-x, 1), round(-z, 1)]
        out.append(row)
    return {"polys": out, "islands": len(order),
            "links": [[round(-a[0], 1), round(-a[2], 1), round(a[1], 1), round(-b[0], 1), round(-b[2], 1), round(b[1], 1)]
                      for a, b in links]}


class NavStore:
    """Finds and caches zones' navmeshes (re-read when the file changes, e.g. after a fix)."""

    def __init__(self, directory: str | None):
        self.directory = directory
        self.cache: dict[str, tuple[float, dict]] = {}

    def get(self, short_name: str) -> dict:
        path = os.path.join(self.directory or "", f"{short_name}.nav")
        if not self.directory or not os.path.isfile(path):
            return {"polys": [], "links": [], "islands": 0,
                    "error": f"no navmesh for {short_name} in {self.directory or '(EQMQ_NAV not set)'}"}
        mtime = os.path.getmtime(path)
        cached = self.cache.get(short_name)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            data = read_nav(path)
        except (OSError, ValueError, struct.error, zlib.error) as e:
            data = {"polys": [], "links": [], "islands": 0, "error": f"can't read {path}: {e}"}
        self.cache[short_name] = (mtime, data)
        return data
