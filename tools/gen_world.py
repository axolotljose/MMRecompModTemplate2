#!/usr/bin/env python3
"""
World generator for "Lilith's Lullaby: White Rose Sanctuary".

Generates, as plain C (committed to the repo so that building the mod needs nothing but the normal toolchain):

    src/gen/lil_textures.c   procedural 32x32 IA8 detail textures
    src/gen/lil_world.c      the two scenes (White Rose Sanctuary, Thornbound Crypt): meshes, collision, lighting,
                             spawns, the player cutscene chain and the actor placement
    src/gen/lil_models.c     low poly models + dynamic collision used by the custom actors
    include/lil_gen.h        extern declarations for all of the above

Run it from anywhere:   python3 tools/gen_world.py            (writes the files)
                        python3 tools/gen_world.py --check    (validates the layout, writes nothing)

The output is fully deterministic. Everything is expressed in game units (Link is ~60 tall, X east, Y up, Z south).
"""
import math
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
GEN_DIR = os.path.join(ROOT, 'src', 'gen')
INC_DIR = os.path.join(ROOT, 'include')

# ------------------------------------------------------------------------------------------------ vector helpers
def v_sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def v_add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def v_scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def v_dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def v_cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def v_len(a): return math.sqrt(v_dot(a, a))
def v_lerp(a, b, t): return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
def v_norm(a):
    l = v_len(a)
    return (0.0, 1.0, 0.0) if l < 1e-9 else (a[0] / l, a[1] / l, a[2] / l)
def clamp(x, lo, hi): return lo if x < lo else hi if x > hi else x
def rnd(x): return int(math.floor(x + 0.5))

# ------------------------------------------------------------------------------------------------ textures
TEX_SIZE = 32

def _hash(ix, iy, seed):
    n = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    n ^= n >> 16
    return (n & 0xFFFF) / 65535.0

def _vnoise(x, y, cell, seed):
    """Tileable value noise over the 32x32 texture."""
    period = TEX_SIZE // cell
    gx, gy = x / cell, y / cell
    ix, iy = int(math.floor(gx)), int(math.floor(gy))
    fx, fy = gx - ix, gy - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    def h(a, b): return _hash(a % period, b % period, seed)
    top = h(ix, iy) * (1 - fx) + h(ix + 1, iy) * fx
    bot = h(ix, iy + 1) * (1 - fx) + h(ix + 1, iy + 1) * fx
    return top * (1 - fy) + bot * fy

def tex_brick(x, y):
    row = y // 8
    off = 8 if (row & 1) else 0
    bx = (x + off) % 16
    by = y % 8
    if by == 0 or bx == 0:
        return 4
    n = _vnoise(x, y, 4, 11)
    return int(9 + n * 5)

def tex_flag(x, y):
    bx, by = x % 16, y % 16
    if bx == 0 or by == 0:
        return 5
    n = _vnoise(x, y, 8, 23)
    return int(10 + n * 4 + (2 if ((x // 16) + (y // 16)) & 1 else 0) * 0.5)

def tex_cobble(x, y):
    pts = [(_hash(i, 1, 5) * 32, _hash(i, 2, 5) * 32) for i in range(10)]
    best, second = 1e9, 1e9
    for px, py in pts:
        for ox in (-32, 0, 32):
            for oy in (-32, 0, 32):
                d = math.hypot(x - (px + ox), y - (py + oy))
                if d < best: best, second = d, best
                elif d < second: second = d
    edge = second - best
    if edge < 1.6:
        return 4
    return int(clamp(8 + edge * 0.35 + _vnoise(x, y, 4, 7) * 3, 6, 14))

def tex_grass(x, y):
    n = _vnoise(x, y, 4, 31) * 0.6 + _vnoise(x, y, 2, 32) * 0.4
    return int(7 + n * 6)

def tex_hedge(x, y):
    n = _vnoise(x, y, 4, 41) * 0.55 + _vnoise(x, y, 2, 42) * 0.45
    return int(4 + n * 9)

def tex_marble(x, y):
    n = _vnoise(x, y, 8, 51)
    vein = abs(math.sin((x + n * 20) * 0.35 + (y * 0.12)))
    return int(clamp(11 + vein * 4 - (1 if vein < 0.08 else 0) * 3, 7, 15))

def tex_plain(x, y):
    return 15

def tex_rune(x, y):
    dx, dy = x - 15.5, y - 15.5
    r = math.hypot(dx, dy)
    ang = math.atan2(dy, dx)
    v = 9
    if 11 <= r <= 13: v = 15
    if 5 <= r <= 6: v = 13
    if r < 12 and abs(math.sin(ang * 4)) < 0.12: v = 14
    return v

def tex_water(x, y):
    return int(9 + 4 * (0.5 + 0.5 * math.sin(x * 0.5 + _vnoise(x, y, 8, 61) * 6) * math.cos(y * 0.4)))

TEXTURES = {
    'brick': tex_brick, 'flag': tex_flag, 'cobble': tex_cobble, 'grass': tex_grass, 'hedge': tex_hedge,
    'marble': tex_marble, 'plain': tex_plain, 'rune': tex_rune, 'water': tex_water,
}

def texture_bytes(name):
    fn = TEXTURES[name]
    out = bytearray()
    for y in range(TEX_SIZE):
        for x in range(TEX_SIZE):
            i = int(clamp(fn(x, y), 0, 15))
            out.append((i << 4) | 0x0F)        # IA8: 4 bit intensity, 4 bit alpha (opaque)
    return bytes(out)

# name: (texture, base colour, world units per texture repeat)
MATS = {
    'crypt_wall':  ('brick',  (170, 150, 165), 128),
    'crypt_floor': ('flag',   (150, 140, 165), 128),
    'crypt_ceil':  ('cobble', (95, 88, 108), 192),
    'gallery_wall':('brick',  (185, 140, 160), 128),
    'gallery_floor':('marble',(215, 200, 225), 160),
    'knight_wall': ('brick',  (140, 150, 185), 128),
    'knight_floor':('flag',   (130, 140, 175), 128),
    'path_wall':   ('brick',  (150, 175, 160), 128),
    'path_floor':  ('marble', (190, 215, 200), 160),
    'bramble_wall':('hedge',  (70, 110, 70), 128),
    'bramble_floor':('cobble',(110, 120, 90), 160),
    'warden_wall': ('brick',  (190, 150, 110), 128),
    'warden_floor':('flag',   (170, 140, 105), 128),
    'boss_wall':   ('brick',  (140, 90, 130), 128),
    'boss_floor':  ('rune',   (190, 120, 175), 256),
    'boss_ceil':   ('cobble', (70, 45, 75), 192),
    'marble':      ('marble', (235, 232, 245), 128),
    'grass':       ('grass',  (80, 135, 85), 160),
    'hedge':       ('hedge',  (62, 122, 76), 128),
    'plaza':       ('flag',   (215, 210, 232), 128),
    'water':       ('water',  (110, 150, 230), 128),
    'rose_red':    ('plain',  (200, 40, 70), 64),
    'rose_white':  ('plain',  (245, 240, 250), 64),
    'leaf':        ('hedge',  (40, 100, 60), 64),
    'trunk':       ('cobble', (90, 70, 60), 64),
    'plain_dark':  ('plain',  (60, 55, 70), 64),
    'glow':        ('plain',  (255, 230, 250), 64),
}

# ------------------------------------------------------------------------------------------------ surface / collision
SURFACE_STONE = 2
SURFACE_GRASS = 8
SURFACE_DIRT = 0

class Collision:
    """Static collision mesh builder (CollisionHeader + polys + surface types)."""
    def __init__(self, name):
        self.name = name
        self.verts = []
        self.vindex = {}
        self.polys = []       # (a, b, c, surfaceIndex)
        self.surfaces = []    # (light, material, wallFlag)
        self.sindex = {}

    def surface(self, light=0, material=SURFACE_STONE):
        key = (light, material)
        if key not in self.sindex:
            self.sindex[key] = len(self.surfaces)
            self.surfaces.append(key)
        return self.sindex[key]

    def vert(self, p):
        k = (rnd(p[0]), rnd(p[1]), rnd(p[2]))
        if k not in self.vindex:
            self.vindex[k] = len(self.verts)
            self.verts.append(k)
        return self.vindex[k]

    def tri(self, p0, p1, p2, surf):
        a, b, c = self.vert(p0), self.vert(p1), self.vert(p2)
        if len({a, b, c}) < 3:
            return
        n = v_cross(v_sub(self.verts[b], self.verts[a]), v_sub(self.verts[c], self.verts[a]))
        if v_len(n) < 1.0:
            return
        self.polys.append((a, b, c, surf))

    def finalize(self):
        """Returns (vertexList, polyList, surfaceList, minBounds, maxBounds). Computes normals/dist."""
        polys = []
        for a, b, c, surf in self.polys:
            pa, pb, pc = (self.verts[a], self.verts[b], self.verts[c])
            n = v_norm(v_cross(v_sub(pb, pa), v_sub(pc, pa)))
            nx, ny, nz = (clamp(rnd(n[0] * 0x7FFF), -0x7FFF, 0x7FFF), clamp(rnd(n[1] * 0x7FFF), -0x7FFF, 0x7FFF),
                          clamp(rnd(n[2] * 0x7FFF), -0x7FFF, 0x7FFF))
            dist = -rnd(n[0] * pa[0] + n[1] * pa[1] + n[2] * pa[2])
            polys.append((surf, a, b, c, nx, ny, nz, dist))
        xs = [v[0] for v in self.verts]; ys = [v[1] for v in self.verts]; zs = [v[2] for v in self.verts]
        mn = (min(xs) - 2, min(ys) - 2, min(zs) - 2)
        mx = (max(xs) + 2, max(ys) + 2, max(zs) + 2)
        return self.verts, polys, self.surfaces, mn, mx

# ------------------------------------------------------------------------------------------------ mesh builders
LIGHT_DIR = v_norm((0.35, 0.85, 0.40))

class Mesh:
    """Lit-by-vertex-colour (scene) or vertex-normal (actor model) triangle soup, grouped by material."""
    def __init__(self, name):
        self.name = name
        self.tris = {}          # material -> list of (pos[3], uv[3], normal, shade)

    def add_tri(self, mat, pts, normal, uvs, shade_fn):
        self.tris.setdefault(mat, []).append((pts, uvs, normal, shade_fn))

class SceneBuilder:
    def __init__(self, name, scene_const):
        self.name = name
        self.scene_const = scene_const
        self.mesh = Mesh(name)
        self.col = Collision(name)
        self.glows = []             # (pos, radius, (r,g,b))
        self.actors = []            # (slot, x, y, z, yawDeg, params)
        self.spawns = []            # (x, y, z, yawDeg, startMode)
        self.lights = []            # EnvLightSettings dicts
        self.tint_zones = []        # (minx, maxx, minz, maxz, (r,g,b) multiplier)
        self.objects = []
        self.height_hint = 360.0

    # -- lighting -----------------------------------------------------------------------------------------------
    def _shade(self, mat, normal, pos):
        base = MATS[mat][1]
        d = max(0.0, v_dot(normal, LIGHT_DIR))
        s = 0.50 + 0.50 * d
        # vertical gradient: slightly darker towards the ceiling / floor joints
        s *= 0.80 + 0.20 * clamp(1.0 - abs(pos[1] - 150.0) / 260.0, 0.0, 1.0)
        r, g, b = base[0] * s, base[1] * s, base[2] * s
        for (gp, radius, gc) in self.glows:
            dist = v_len(v_sub(pos, gp))
            if dist < radius:
                f = (1.0 - dist / radius) ** 2
                r += gc[0] * f * 0.55; g += gc[1] * f * 0.55; b += gc[2] * f * 0.55
        for (x0, x1, z0, z1, m) in self.tint_zones:
            if x0 <= pos[0] <= x1 and z0 <= pos[2] <= z1:
                r *= m[0]; g *= m[1]; b *= m[2]
        return (int(clamp(r, 0, 255)), int(clamp(g, 0, 255)), int(clamp(b, 0, 255)))

    # -- faces ---------------------------------------------------------------------------------------------------
    def face(self, pts, mat, facing=None, collide=None, max_edge=320.0, uv_shift=(0, 0)):
        """Adds a planar polygon (3 or 4 points), oriented so its normal points along `facing` (a direction)."""
        pts = [tuple(float(c) for c in p) for p in pts]
        n = v_cross(v_sub(pts[1], pts[0]), v_sub(pts[2], pts[0]))
        if v_len(n) < 1e-6 and len(pts) == 4:
            n = v_cross(v_sub(pts[2], pts[1]), v_sub(pts[3], pts[1]))
        if v_len(n) < 1e-6:
            return
        n = v_norm(n)
        if facing is not None and v_dot(n, facing) < 0:
            pts = list(reversed(pts)); n = v_scale(n, -1)
        if len(pts) == 4 and max_edge:
            ea = max(v_len(v_sub(pts[1], pts[0])), v_len(v_sub(pts[3], pts[2])))
            eb = max(v_len(v_sub(pts[3], pts[0])), v_len(v_sub(pts[2], pts[1])))
            na, nb = max(1, int(math.ceil(ea / max_edge))), max(1, int(math.ceil(eb / max_edge)))
            for i in range(na):
                for j in range(nb):
                    def P(u, v):
                        a = v_lerp(pts[0], pts[1], u); b = v_lerp(pts[3], pts[2], u)
                        return v_lerp(a, b, v)
                    q = [P(i / na, j / nb), P((i + 1) / na, j / nb), P((i + 1) / na, (j + 1) / nb), P(i / na, (j + 1) / nb)]
                    self._emit(q, n, mat, collide, uv_shift)
        else:
            self._emit(pts, n, mat, collide, uv_shift)

    def _emit(self, pts, n, mat, collide, uv_shift):
        tris = [(pts[0], pts[1], pts[2])] + ([(pts[0], pts[2], pts[3])] if len(pts) == 4 else [])
        scale = MATS[mat][2]
        ax, ay, az = abs(n[0]), abs(n[1]), abs(n[2])
        def uvof(p):
            if ay >= 0.6: u, v = p[0], p[2]
            elif ax > az: u, v = p[2], p[1]
            else: u, v = p[0], p[1]
            return ((u + uv_shift[0]) / scale * TEX_SIZE * 32.0, (v + uv_shift[1]) / scale * TEX_SIZE * 32.0)
        uvs_all = [uvof(p) for p in pts]
        su = math.floor(min(u for u, _ in uvs_all) / 1024.0) * 1024.0
        sv = math.floor(min(v for _, v in uvs_all) / 1024.0) * 1024.0
        for t in tris:
            uvs = [(rnd(uvof(p)[0] - su), rnd(uvof(p)[1] - sv)) for p in t]
            self.mesh.add_tri(mat, [tuple(p) for p in t], n, uvs, lambda pos, m=mat, nn=n: self._shade(m, nn, pos))
            if collide is not None:
                self.col.tri(t[0], t[1], t[2], collide)

    def collide_only(self, pts, facing, surf):
        pts = [tuple(float(c) for c in p) for p in pts]
        n = v_norm(v_cross(v_sub(pts[1], pts[0]), v_sub(pts[2], pts[0])))
        if v_dot(n, facing) < 0: pts = list(reversed(pts))
        self.col.tri(pts[0], pts[1], pts[2], surf)
        if len(pts) == 4: self.col.tri(pts[0], pts[2], pts[3], surf)

    # -- solids --------------------------------------------------------------------------------------------------
    def box(self, x0, y0, z0, x1, y1, z1, mat, top_mat=None, collide=None, faces='nsewt'):
        cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
        defs = {
            'n': ([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], (0, 0, -1)),
            's': ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
            'w': ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1, 0, 0)),
            'e': ([(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], (1, 0, 0)),
            't': ([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], (0, 1, 0)),
            'b': ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
        }
        for k in faces:
            pts, nrm = defs[k]
            self.face(pts, (top_mat if (k == 't' and top_mat) else mat), facing=nrm, collide=collide)

    def cone(self, cx, y0, cz, radius, height, mat, sides=8, collide=None):
        apex = (cx, y0 + height, cz)
        ring = [(cx + radius * math.cos(2 * math.pi * i / sides), y0, cz + radius * math.sin(2 * math.pi * i / sides))
                for i in range(sides)]
        for i in range(sides):
            a, b = ring[i], ring[(i + 1) % sides]
            mid = v_lerp(a, b, 0.5)
            self.face([a, b, apex], mat, facing=v_sub(mid, (cx, y0 + height * 0.3, cz)), max_edge=0, collide=collide)

    def sphere(self, cx, cy, cz, r, mat, rings=4, segs=8):
        for i in range(rings):
            a0, a1 = math.pi * i / rings, math.pi * (i + 1) / rings
            for j in range(segs):
                b0, b1 = 2 * math.pi * j / segs, 2 * math.pi * (j + 1) / segs
                def P(a, b): return (cx + r * math.sin(a) * math.cos(b), cy + r * math.cos(a), cz + r * math.sin(a) * math.sin(b))
                q = [P(a0, b0), P(a0, b1), P(a1, b1), P(a1, b0)]
                ctr = ((q[0][0] + q[2][0]) / 2, (q[0][1] + q[2][1]) / 2, (q[0][2] + q[2][2]) / 2)
                quad = q if i not in (0, rings - 1) else ([q[0], q[2], q[3]] if i == 0 else [q[0], q[1], q[2]])
                self.face(quad, mat, facing=v_sub(ctr, (cx, cy, cz)), max_edge=0)

    # -- rooms ---------------------------------------------------------------------------------------------------
    def shell(self, foot, y0, height, floor_mat, wall_mat, ceil_mat=None, doors=(), light=0, ceiling=True,
              floor_material=SURFACE_STONE, wall_top_mat=None, ceil_collide=True):
        """
        Interior shell of a convex footprint (list of (x, z)). `doors` is a list of (edgeIndex, offsetFromEdgeStart,
        width, doorHeight) gaps cut into the walls (no geometry is generated for them - tunnels join up there).
        """
        cx = sum(p[0] for p in foot) / len(foot); cz = sum(p[1] for p in foot) / len(foot)
        fs = self.col.surface(light, floor_material)
        ws = self.col.surface(light, SURFACE_STONE)
        # floor: fan triangulation of the convex polygon (subdivided by face() for quads; triangles stay whole)
        if len(foot) == 4:
            self.face([(p[0], y0, p[1]) for p in foot], floor_mat, facing=(0, 1, 0), collide=fs)
        else:
            for i in range(len(foot)):
                a, b = foot[i], foot[(i + 1) % len(foot)]
                tri = [(cx, y0, cz), (a[0], y0, a[1]), (b[0], y0, b[1])]
                self._subdivided_tri(tri, floor_mat, (0, 1, 0), fs)
        if ceiling:
            cmat = ceil_mat or wall_mat
            if len(foot) == 4:
                self.face([(p[0], y0 + height, p[1]) for p in foot], cmat, facing=(0, -1, 0), collide=(ws if ceil_collide else None))
            else:
                for i in range(len(foot)):
                    a, b = foot[i], foot[(i + 1) % len(foot)]
                    tri = [(cx, y0 + height, cz), (a[0], y0 + height, a[1]), (b[0], y0 + height, b[1])]
                    self._subdivided_tri(tri, cmat, (0, -1, 0), ws if ceil_collide else None)
        for ei in range(len(foot)):
            a, b = foot[ei], foot[(ei + 1) % len(foot)]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            tx, tz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            inward = (cx - mid[0], 0, cz - mid[1])
            gaps = sorted([(off - w / 2, off + w / 2, dh) for (e, off, w, dh) in doors if e == ei])
            cursor = 0.0
            def P(t, y): return (a[0] + tx * t, y, a[1] + tz * t)
            for (g0, g1, dh) in gaps:
                if g0 > cursor:
                    self.face([P(cursor, y0), P(g0, y0), P(g0, y0 + height), P(cursor, y0 + height)], wall_mat, facing=inward, collide=ws)
                self.face([P(g0, y0 + dh), P(g1, y0 + dh), P(g1, y0 + height), P(g0, y0 + height)], wall_mat, facing=inward, collide=ws)
                cursor = g1
            if cursor < length:
                self.face([P(cursor, y0), P(length, y0), P(length, y0 + height), P(cursor, y0 + height)], wall_mat, facing=inward, collide=ws)

    def _subdivided_tri(self, tri, mat, facing, collide, depth=2):
        def split(t, d):
            if d == 0:
                self.face(list(t), mat, facing=facing, collide=collide, max_edge=0); return
            a, b, c = t
            ab, bc, ca = v_lerp(a, b, .5), v_lerp(b, c, .5), v_lerp(c, a, .5)
            for s in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)):
                split(s, d - 1)
        split(tuple(tri), depth)

    def tunnel(self, x_center, width, z_a, z_b, y0, height, floor_mat, wall_mat, ceil_mat, light=0, floor_material=SURFACE_STONE):
        """Straight tunnel along Z between z_a and z_b (open at both ends), centred on x_center."""
        zmin, zmax = min(z_a, z_b), max(z_a, z_b)
        x0, x1 = x_center - width / 2, x_center + width / 2
        fs = self.col.surface(light, floor_material); ws = self.col.surface(light, SURFACE_STONE)
        self.face([(x0, y0, zmin), (x1, y0, zmin), (x1, y0, zmax), (x0, y0, zmax)], floor_mat, facing=(0, 1, 0), collide=fs)
        self.face([(x0, y0 + height, zmin), (x1, y0 + height, zmin), (x1, y0 + height, zmax), (x0, y0 + height, zmax)], ceil_mat, facing=(0, -1, 0), collide=ws)
        self.face([(x0, y0, zmin), (x0, y0, zmax), (x0, y0 + height, zmax), (x0, y0 + height, zmin)], wall_mat, facing=(1, 0, 0), collide=ws)
        self.face([(x1, y0, zmin), (x1, y0, zmax), (x1, y0 + height, zmax), (x1, y0 + height, zmin)], wall_mat, facing=(-1, 0, 0), collide=ws)

    def pillar(self, cx, cz, half, y0, y1, mat, collide=None, cap_mat=None):
        self.box(cx - half, y0, cz - half, cx + half, y1, cz + half, mat, top_mat=cap_mat or mat, collide=collide, faces='nsewt')

    # -- actor / spawn helpers -------------------------------------------------------------------------------------
    def actor(self, slot, x, y, z, yaw=0, params=0):
        self.actors.append((slot, int(x), int(y), int(z), int(yaw) % 360, params & 0xFFFF))

    def spawn(self, x, y, z, yaw, start_mode):
        self.spawns.append((int(x), int(y), int(z), int(yaw) % 360, start_mode))

def octagon(cx, cz, r, sides=12):
    off = math.pi / sides
    return [(cx + r * math.cos(2 * math.pi * i / sides + off), cz + r * math.sin(2 * math.pi * i / sides + off)) for i in range(sides)]

def edge_index_facing(foot, direction):
    """Index of the footprint edge whose outward normal best matches `direction` (x, z)."""
    cx = sum(p[0] for p in foot) / len(foot); cz = sum(p[1] for p in foot) / len(foot)
    best, bi = -9, 0
    for i in range(len(foot)):
        a, b = foot[i], foot[(i + 1) % len(foot)]
        mx, mz = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cz
        l = math.hypot(mx, mz)
        d = (mx / l) * direction[0] + (mz / l) * direction[1]
        if d > best: best, bi = d, i
    return bi

def edge_mid_offset(foot, ei):
    a, b = foot[ei], foot[(ei + 1) % len(foot)]
    return math.hypot(b[0] - a[0], b[1] - a[1]) / 2

# ------------------------------------------------------------------------------------------------------------ flags
FLAG_SANCTUARY_GATE = 0x01
FLAG_ENTRY_PLATE = 0x02
FLAG_GALLERY_CLEAR = 0x03
FLAG_PATH_SOLVED = 0x04
FLAG_KNIGHTS_CLEAR = 0x05
FLAG_WARDEN_DEAD = 0x06
FLAG_QUEEN_DEAD = 0x07

# actor slot names (must match LilActorSlot in include/lilith.h)
A_STATUE, A_PORTAL, A_BARRIER, A_PLATE, A_PATH, A_BRAMBLE, A_ARENA, A_THORNLING, A_WISP, A_KNIGHT, A_HAZARD, \
    A_WARDEN, A_QUEEN = range(13)
ACTOR_SLOT_NAMES = ['LIL_ACT_LILITH_STATUE', 'LIL_ACT_RETURN_PORTAL', 'LIL_ACT_BARRIER', 'LIL_ACT_PLATE', 'LIL_ACT_PATH_PUZZLE',
                    'LIL_ACT_BRAMBLE', 'LIL_ACT_ARENA', 'LIL_ACT_THORNLING', 'LIL_ACT_PETAL_WISP', 'LIL_ACT_ROSE_KNIGHT',
                    'LIL_ACT_HAZARD', 'LIL_ACT_BOSS_WARDEN', 'LIL_ACT_BOSS_QUEEN']
# vanilla actors used directly in placement
ACT_VANILLA_BOMBFLOWER = 'ACTOR_EN_BOMBF'
ACT_VANILLA_ITEM00 = 'ACTOR_EN_ITEM00'

PORTAL_TO_CRYPT, PORTAL_TO_SANCTUARY, PORTAL_HOME = 0, 1, 2
BARRIER_CRYPT, BARRIER_SANCTUARY = 0, 1

# ------------------------------------------------------------------------------------------------ the Sanctuary
def build_sanctuary():
    sc = SceneBuilder('Sanctuary', 'LIL_SCENE_SANCTUARY')
    HALF = 900.0
    H = 420.0
    grass = sc.col.surface(0, SURFACE_GRASS)
    stone = sc.col.surface(0, SURFACE_STONE)
    # lighting for baked colours: a soft moonlit garden
    sc.glows += [((0, 120, -150), 420, (150, 160, 255)), ((0, 40, -1250), 300, (255, 120, 190))]

    # ground (grass), plaza and path
    sc.face([(-HALF, 0, -HALF), (HALF, 0, -HALF), (HALF, 0, HALF), (-HALF, 0, HALF)], 'grass', facing=(0, 1, 0), collide=grass, max_edge=300)
    sc.face([(-360, 2, -360), (360, 2, -360), (360, 2, 360), (-360, 2, 360)], 'plaza', facing=(0, 1, 0), collide=stone, max_edge=240)
    sc.face([(-90, 2, -HALF), (90, 2, -HALF), (90, 2, -360), (-90, 2, -360)], 'marble', facing=(0, 1, 0), collide=stone, max_edge=240)
    sc.face([(-90, 2, 360), (90, 2, 360), (90, 2, HALF - 120), (-90, 2, HALF - 120)], 'marble', facing=(0, 1, 0), collide=stone, max_edge=240)
    # moonlit pool decoration (visual only, sits just above the plaza)
    sc.face([(180, 3, 80), (300, 3, 80), (300, 3, 240), (180, 3, 240)], 'water', facing=(0, 1, 0), max_edge=0)

    # hedge walls; the north wall has the crypt gate opening
    ws = stone
    for (p0, p1, inward, gap) in (
        ((-HALF, -HALF), (-HALF, HALF), (1, 0, 0), None),       # west
        ((HALF, -HALF), (HALF, HALF), (-1, 0, 0), None),        # east
        ((-HALF, HALF), (HALF, HALF), (0, 0, -1), None),        # south
    ):
        sc.face([(p0[0], 0, p0[1]), (p1[0], 0, p1[1]), (p1[0], H, p1[1]), (p0[0], H, p0[1])], 'hedge', facing=inward, collide=ws, max_edge=300)
    GAP = 120.0; GAPH = 300.0
    sc.face([(-HALF, 0, -HALF), (-GAP, 0, -HALF), (-GAP, H, -HALF), (-HALF, H, -HALF)], 'hedge', facing=(0, 0, 1), collide=ws, max_edge=300)
    sc.face([(GAP, 0, -HALF), (HALF, 0, -HALF), (HALF, H, -HALF), (GAP, H, -HALF)], 'hedge', facing=(0, 0, 1), collide=ws, max_edge=300)
    sc.face([(-GAP, GAPH, -HALF), (GAP, GAPH, -HALF), (GAP, H, -HALF), (-GAP, H, -HALF)], 'hedge', facing=(0, 0, 1), collide=ws, max_edge=300)
    # invisible ceiling so nothing can leave the garden
    sc.collide_only([(-HALF, 900, -HALF), (HALF, 900, -HALF), (HALF, 900, HALF), (-HALF, 900, HALF)], (0, -1, 0), ws)

    # the crypt stair-tunnel behind the gate
    sc.tunnel(0, 2 * GAP, -HALF, -1300, 0, GAPH, 'marble', 'crypt_wall', 'crypt_ceil', light=0)
    sc.face([(-GAP, 0, -1300), (GAP, 0, -1300), (GAP, GAPH, -1300), (-GAP, GAPH, -1300)], 'glow', facing=(0, 0, 1), collide=ws, max_edge=0)
    sc.collide_only([(-GAP - 10, 0, -1310), (GAP + 10, 0, -1310), (GAP + 10, GAPH, -1310), (-GAP - 10, GAPH, -1310)], (0, 0, 1), ws)

    # Lilith's plinth
    sc.box(-90, 2, -240, 90, 34, -60, 'marble', collide=stone)
    # four pillars round the plaza + rose bushes, cypresses
    for sx in (-1, 1):
        for sz in (-1, 1):
            sc.pillar(sx * 330, sz * 330, 26, 2, 300, 'marble', collide=stone, cap_mat='rose_white')
    rng = random.Random(7)
    bush_spots = [(-560, 300), (560, 300), (-600, -150), (600, -150), (-420, -600), (420, -600), (-700, 520), (700, 520),
                  (-240, 620), (240, 620), (-740, -700), (740, -700), (-150, -560), (150, -560), (-520, 40), (520, 40)]
    for (bx, bz) in bush_spots:
        sc.sphere(bx, 26, bz, 34, 'leaf', rings=3, segs=7)
        for k in range(5):
            ang = rng.uniform(0, 2 * math.pi); rr = rng.uniform(14, 28)
            mat = 'rose_white' if (k + int(bx)) % 3 else 'rose_red'
            sc.sphere(bx + rr * math.cos(ang), 40 + rng.uniform(0, 16), bz + rr * math.sin(ang), 9, mat, rings=2, segs=5)
    for k in range(10):
        z = -800 + k * 170
        for x in (-840, 840):
            sc.cone(x, 0, z, 40, 360, 'leaf', sides=6)

    sc.objects = ['GAMEPLAY_KEEP']
    # actors
    sc.actor(A_STATUE, 0, 34, -150, 0, FLAG_SANCTUARY_GATE)
    sc.actor(A_BARRIER, 0, 0, -HALF + 6, 0, (BARRIER_SANCTUARY << 8) | FLAG_SANCTUARY_GATE)
    sc.actor(A_PORTAL, 0, 0, -1262, 0, PORTAL_TO_CRYPT)
    sc.actor(A_PORTAL, 520, 2, 420, 0, PORTAL_HOME)
    # spawns: 0 = song arrival (Soaring style arrival), 1 = from the crypt
    sc.spawn(0, 2, 430, 180, 'PLAYER_START_MODE_OWL')
    sc.spawn(0, 2, -800, 0, 'PLAYER_START_MODE_D')
    # light settings: [ambient], light1(dir,color), light2(dir,color), fog, fogNear, zFar
    sc.lights.append(dict(amb=(72, 82, 130), l1d=(40, 90, 40), l1c=(150, 165, 225), l2d=(-60, -40, -50), l2c=(70, 55, 100),
                          fog=(14, 18, 44), fog_near=760, zfar=4200, blend=64))
    sc.cam = 'CAM_SET_NORMAL0'
    sc.music = 'NA_BGM_FAIRY_FOUNTAIN'
    sc.room_type = 'ROOM_TYPE_NORMAL'
    sc.echo = 0x10
    sc.ceiling_y = 900
    return sc

# -------------------------------------------------------------------------------------------------- the Crypt
def build_crypt():
    sc = SceneBuilder('Crypt', 'LIL_SCENE_CRYPT')
    DOOR_W, DOOR_H = 240.0, 280.0
    H = 360.0
    # sections: (name, footprint, floor, wall, ceil, light, tall)
    def rect(x0, z0, x1, z1): return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    # section footprints (CCW as listed is irrelevant: faces are oriented towards the section centre)
    s1 = rect(-400, -400, 400, 400)
    s2 = rect(-350, -1600, 350, -600)
    s3 = rect(-450, -2800, 450, -1800)
    s4 = rect(-400, -3800, 400, -3000)
    s5 = rect(-120, -4800, 120, -4000)
    s6 = octagon(0, -5400, 600)
    s7 = octagon(0, -6900, 700)
    stone = sc.col.surface(0, SURFACE_STONE)

    def door_on_rect_north(foot, x_off_from_west=None):
        # rect footprints are listed (x0,z0),(x1,z0),(x1,z1),(x0,z1): edge 0 is the north edge (z0), edge 2 the south edge
        w = foot[1][0] - foot[0][0]
        return (0, w / 2, DOOR_W, DOOR_H)
    def door_on_rect_south(foot):
        w = foot[1][0] - foot[0][0]
        return (2, w / 2, DOOR_W, DOOR_H)

    # Section 1: entry hall (door north)
    sc.shell(s1, 0, H, 'crypt_floor', 'crypt_wall', 'crypt_ceil', doors=[door_on_rect_north(s1)], light=0)
    # Section 2: petal gallery (doors south and north)
    sc.shell(s2, 0, H, 'gallery_floor', 'gallery_wall', 'crypt_ceil', doors=[door_on_rect_south(s2), door_on_rect_north(s2)], light=1)
    # Section 3: sentinel hall
    sc.shell(s3, 0, H, 'knight_floor', 'knight_wall', 'crypt_ceil', doors=[door_on_rect_south(s3), door_on_rect_north(s3)], light=2)
    # Section 4: path room
    sc.shell(s4, 0, H, 'path_floor', 'path_wall', 'crypt_ceil', doors=[door_on_rect_south(s4), (0, 400, 240.0, DOOR_H)], light=3)
    # Section 5: bramble hall: a narrow hall that opens straight into the warden arena (door north and south)
    sc.shell(s5, 0, H, 'bramble_floor', 'bramble_wall', 'crypt_ceil', doors=[(2, 120, 240.0, DOOR_H), (0, 120, 240.0, DOOR_H)], light=4)
    # Section 6: warden arena (octagon), door south (towards the bramble hall) and north
    s6_south = edge_index_facing(s6, (0, 1)); s6_north = edge_index_facing(s6, (0, -1))
    sc.shell(s6, 0, 420, 'warden_floor', 'warden_wall', 'crypt_ceil',
             doors=[(s6_south, edge_mid_offset(s6, s6_south), 240.0, DOOR_H), (s6_north, edge_mid_offset(s6, s6_north), 240.0, DOOR_H)], light=5)
    # Section 7: boss arena (octagon), door south
    s7_south = edge_index_facing(s7, (0, 1))
    sc.shell(s7, 0, 620, 'boss_floor', 'boss_wall', 'boss_ceil', doors=[(s7_south, edge_mid_offset(s7, s7_south), 240.0, DOOR_H)], light=6)

    # tunnels linking the sections (width 240 = door width)
    sc.tunnel(0, DOOR_W, -400, -600, 0, DOOR_H + 20, 'crypt_floor', 'crypt_wall', 'crypt_ceil', light=0)
    sc.tunnel(0, DOOR_W, -1600, -1800, 0, DOOR_H + 20, 'crypt_floor', 'crypt_wall', 'crypt_ceil', light=1)
    sc.tunnel(0, DOOR_W, -2800, -3000, 0, DOOR_H + 20, 'crypt_floor', 'crypt_wall', 'crypt_ceil', light=2)
    sc.tunnel(0, DOOR_W, -3800, -4000, 0, DOOR_H + 20, 'crypt_floor', 'crypt_wall', 'crypt_ceil', light=3)
    # the warden arena's south edge sits at z = -4800 + (R*cos(pi/12) - R) so join the hall to it with a short tunnel
    s6_south_z = max(p[1] for p in s6)
    if abs(s6_south_z + 4800) > 4:
        sc.tunnel(0, DOOR_W, -4800, s6_south_z, 0, DOOR_H + 20, 'bramble_floor', 'bramble_wall', 'crypt_ceil', light=4)
    s6_north_z = min(p[1] for p in s6); s7_south_z = max(p[1] for p in s7)
    sc.tunnel(0, DOOR_W, s6_north_z, s7_south_z, 0, DOOR_H + 20, 'crypt_floor', 'crypt_wall', 'crypt_ceil', light=5)

    # decoration: pillars and braziers (glow points) per section
    for (z, xs) in ((-200, (-250, 250)), (-1000, (-220, 220)), (-2300, (-300, 300)), (-3400, (-250, 250))):
        for x in xs:
            sc.pillar(x, z, 28, 0, H, 'marble' if z > -2000 else 'crypt_wall', collide=stone, cap_mat='rose_white')
            sc.glows.append(((x, 200, z), 260, (255, 150, 170)))
    # raised dais in the warden arena and the boss arena (visual + collision)
    sc.box(-140, 0, -5540, 140, 18, -5260, 'warden_floor', collide=stone)
    sc.box(-180, 0, -7080, 180, 22, -6720, 'boss_floor', collide=stone)
    for (x, z) in ((-400, -5400), (400, -5400), (0, -5800)):
        sc.pillar(x, z, 30, 0, 420, 'warden_wall', collide=stone, cap_mat='rose_white')
        sc.glows.append(((x, 220, z), 280, (255, 190, 120)))
    for k in range(6):
        ang = 2 * math.pi * k / 6 + math.pi / 6
        x, z = 520 * math.cos(ang), -6900 + 520 * math.sin(ang)
        sc.pillar(x, z, 34, 0, 620, 'boss_wall', collide=stone, cap_mat='glow')
        sc.glows.append(((x, 300, z), 320, (230, 100, 200)))
    sc.glows += [((0, 250, 0), 500, (200, 120, 170)), ((0, 250, -1100), 500, (230, 120, 190)), ((0, 250, -2300), 500, (120, 140, 230)),
                 ((0, 250, -3400), 500, (130, 220, 170)), ((0, 250, -4400), 400, (100, 180, 100)),
                 ((0, 260, -5400), 650, (255, 170, 90)), ((0, 300, -6900), 800, (220, 90, 190))]
    # thorn decoration: cones along the sides of the bramble hall
    for k in range(6):
        z = -4100 - k * 110
        sc.cone(-100, 0, z, 16, 70, 'leaf', sides=5); sc.cone(100, 0, z - 40, 16, 70, 'leaf', sides=5)

    sc.objects = ['GAMEPLAY_KEEP', 'OBJECT_BOMBF', 'OBJECT_GI_HEARTS']
    # ---- actors --------------------------------------------------------------------------------------------------
    # entry hall
    sc.actor(A_PORTAL, 0, 0, 350, 0, PORTAL_TO_SANCTUARY)
    sc.actor(A_THORNLING, -250, 0, -180, 0, 0); sc.actor(A_THORNLING, 250, 0, -180, 0, 0)
    sc.actor(A_PLATE, 0, 0, -250, 0, (0 << 8) | FLAG_ENTRY_PLATE)
    sc.actor(A_BARRIER, 0, 0, -414, 0, (BARRIER_CRYPT << 8) | FLAG_ENTRY_PLATE)
    # petal gallery arena (spawns its own waves)
    sc.actor(A_ARENA, 0, 0, -1100, 0, 0)
    sc.actor(A_BARRIER, 0, 0, -1614, 0, (BARRIER_CRYPT << 8) | FLAG_GALLERY_CLEAR)
    # sentinel hall arena
    sc.actor(A_ARENA, 0, 0, -2300, 0, 1)
    sc.actor(A_BARRIER, 0, 0, -2814, 0, (BARRIER_CRYPT << 8) | FLAG_KNIGHTS_CLEAR)
    # path room puzzle
    sc.actor(A_PATH, 0, 0, -3400, 0, FLAG_PATH_SOLVED)
    sc.actor(A_BARRIER, 0, 0, -3814, 0, (BARRIER_CRYPT << 8) | FLAG_PATH_SOLVED)
    # bramble hall
    sc.actor(A_BRAMBLE, 0, 0, -4300, 0, 0); sc.actor(A_BRAMBLE, 0, 0, -4560, 0, 0)
    sc.actor_vanilla = [(ACT_VANILLA_BOMBFLOWER, -70, 0, -4120, 0, 0), (ACT_VANILLA_BOMBFLOWER, 70, 0, -4120, 0, 0),
                        (ACT_VANILLA_BOMBFLOWER, 0, 0, -4430, 0, 0)]
    # warden arena
    sc.actor(A_WARDEN, 0, 18, -5400, 0, FLAG_WARDEN_DEAD)
    sc.actor(A_BARRIER, 0, 0, s6_north_z + 14, 0, (BARRIER_CRYPT << 8) | FLAG_WARDEN_DEAD)
    # boss arena
    sc.actor(A_QUEEN, 0, 22, -6900, 0, FLAG_QUEEN_DEAD)
    # spawn: the entry hall, facing north
    sc.spawn(0, 0, 250, 180, 'PLAYER_START_MODE_D')
    # light settings (7 areas)
    def L(amb, l1c, fog, near=700, far=3200, l1d=(50, 80, 30), l2c=(40, 30, 60)):
        return dict(amb=amb, l1d=l1d, l1c=l1c, l2d=(-50, -40, -60), l2c=l2c, fog=fog, fog_near=near, zfar=far, blend=64)
    sc.lights += [
        L((78, 70, 92), (150, 130, 160), (26, 20, 36)),       # 0 entry hall
        L((92, 70, 96), (190, 140, 170), (34, 20, 36)),       # 1 petal gallery
        L((70, 80, 120), (130, 150, 210), (16, 22, 44)),      # 2 sentinel hall
        L((80, 110, 96), (150, 200, 170), (18, 34, 28)),      # 3 path room
        L((60, 92, 64), (110, 160, 100), (12, 30, 16), near=600),   # 4 bramble hall
        L((120, 92, 64), (220, 170, 110), (40, 24, 12)),      # 5 warden arena
        L((104, 60, 100), (210, 110, 190), (30, 10, 32), far=3600),  # 6 boss arena
    ]
    sc.cam = 'CAM_SET_DUNGEON0'
    sc.music = 'NA_BGM_IKANA_CASTLE'
    sc.room_type = 'ROOM_TYPE_DUNGEON'
    sc.echo = 0x28
    sc.ceiling_y = 620
    return sc

# ------------------------------------------------------------------------------------------------------ models
class Model:
    """Lit (vertex normal) low poly model. Parts are (name, colour, triangles)."""
    def __init__(self, name):
        self.name = name
        self.parts = []   # (partname, (r,g,b), [ (p0,p1,p2) ])

    def part(self, name, colour):
        p = (name, colour, [])
        self.parts.append(p)
        return p[2]

def m_box(tris, x0, y0, z0, x1, y1, z1):
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3), (1, 2, 6, 5), (3, 7, 6, 2), (0, 1, 5, 4)]
    ctr = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    for q in quads:
        _oriented_quad(tris, [c[i] for i in q], ctr)

def _oriented_quad(tris, pts, center):
    n = v_cross(v_sub(pts[1], pts[0]), v_sub(pts[2], pts[0]))
    mid = v_scale(v_add(v_add(pts[0], pts[1]), v_add(pts[2], pts[3])), 0.25)
    if v_dot(n, v_sub(mid, center)) < 0:
        pts = list(reversed(pts))
    tris.append((pts[0], pts[1], pts[2])); tris.append((pts[0], pts[2], pts[3]))

def _oriented_tri(tris, a, b, c, center):
    n = v_cross(v_sub(b, a), v_sub(c, a))
    mid = v_scale(v_add(v_add(a, b), c), 1 / 3.0)
    if v_dot(n, v_sub(mid, center)) < 0:
        b, c = c, b
    tris.append((a, b, c))

def m_cone(tris, cx, y0, cz, r, h, sides=8, apex_dx=0.0, apex_dz=0.0):
    apex = (cx + apex_dx, y0 + h, cz + apex_dz)
    ring = [(cx + r * math.cos(2 * math.pi * i / sides), y0, cz + r * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    center = (cx, y0 + h * 0.3, cz)
    for i in range(sides):
        _oriented_tri(tris, ring[i], ring[(i + 1) % sides], apex, center)
        _oriented_tri(tris, ring[i], ring[(i + 1) % sides], (cx, y0, cz), (cx, y0 + h * 0.5, cz))

def m_cyl(tris, cx, y0, cz, r, h, sides=8, r_top=None):
    rt = r if r_top is None else r_top
    b = [(cx + r * math.cos(2 * math.pi * i / sides), y0, cz + r * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    t = [(cx + rt * math.cos(2 * math.pi * i / sides), y0 + h, cz + rt * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    center = (cx, y0 + h / 2, cz)
    for i in range(sides):
        j = (i + 1) % sides
        _oriented_quad(tris, [b[i], b[j], t[j], t[i]], center)
        _oriented_tri(tris, b[i], b[j], (cx, y0, cz), center)
        _oriented_tri(tris, t[i], t[j], (cx, y0 + h, cz), center)

def m_sphere(tris, cx, cy, cz, r, rings=4, segs=8, sy=1.0, sx=1.0, sz=1.0):
    def P(a, b): return (cx + sx * r * math.sin(a) * math.cos(b), cy + sy * r * math.cos(a), cz + sz * r * math.sin(a) * math.sin(b))
    for i in range(rings):
        a0, a1 = math.pi * i / rings, math.pi * (i + 1) / rings
        for j in range(segs):
            b0, b1 = 2 * math.pi * j / segs, 2 * math.pi * (j + 1) / segs
            q = [P(a0, b0), P(a0, b1), P(a1, b1), P(a1, b0)]
            if i == 0: _oriented_tri(tris, q[0], q[2], q[3], (cx, cy, cz))
            elif i == rings - 1: _oriented_tri(tris, q[0], q[1], q[2], (cx, cy, cz))
            else: _oriented_quad(tris, q, (cx, cy, cz))

def m_petal(tris, length, width, thick, tilt=0.0):
    """A flattened diamond petal pointing along +Z from the origin, optionally tilted up (radians)."""
    pts = [(0, 0, 0), (-width, 0, length * 0.35), (0, 0, length), (width, 0, length * 0.35)]
    def rot(p):
        y = p[1] * math.cos(tilt) - p[2] * math.sin(tilt); z = p[1] * math.sin(tilt) + p[2] * math.cos(tilt)
        return (p[0], y, z)
    top = rot((0, thick, length * 0.35)); bot = rot((0, -thick, length * 0.35))
    ring = [rot(p) for p in pts]
    for i in range(4):
        _oriented_tri(tris, ring[i], ring[(i + 1) % 4], top, rot((0, 0, length * 0.35)))
        _oriented_tri(tris, ring[i], ring[(i + 1) % 4], bot, rot((0, 0, length * 0.35)))

def model_rose_knight():
    m = Model('RoseKnight')
    body = m.part('Body', (150, 155, 190))
    m_box(body, -22, 26, -14, 22, 92, 14)            # torso
    m_box(body, -20, 0, -10, -4, 28, 10); m_box(body, 4, 0, -10, 20, 28, 10)   # legs
    m_box(body, -34, 70, -10, -22, 94, 10); m_box(body, 22, 70, -10, 34, 94, 10)  # shoulders
    head = m.part('Head', (200, 200, 220))
    m_sphere(head, 0, 108, 0, 15, rings=3, segs=7)
    plume = m.part('Plume', (200, 40, 70))
    m_cone(plume, 0, 118, 0, 6, 26, sides=5, apex_dx=0, apex_dz=-14)
    shield = m.part('Shield', (235, 235, 245))
    m_box(shield, 24, 40, 10, 30, 100, 40)
    m_cone(shield, 34, 62, 26, 6, 10, sides=5)
    sword = m.part('Sword', (220, 220, 235))
    m_box(sword, -2, -4, 0, 2, 4, 60)
    m_box(sword, -8, -4, 0, 8, -1, 4)
    return m

def model_thornling():
    m = Model('Thornling')
    body = m.part('Body', (70, 120, 60))
    m_sphere(body, 0, 26, 0, 24, rings=4, segs=8)
    thorns = m.part('Thorns', (120, 70, 50))
    rng = random.Random(3)
    for i in range(14):
        a = rng.uniform(0, 2 * math.pi); e = rng.uniform(-0.3, 1.2)
        d = (math.cos(a) * math.cos(e), math.sin(e), math.sin(a) * math.cos(e))
        base = (d[0] * 22, 26 + d[1] * 22, d[2] * 22)
        tip = (d[0] * 42, 26 + d[1] * 42, d[2] * 42)
        # thin spike as a 3-sided cone along d
        ax = v_norm(v_cross(d, (0, 1, 0.3))); ay = v_norm(v_cross(d, ax))
        ring = [v_add(base, v_add(v_scale(ax, 5 * math.cos(2 * math.pi * k / 3)), v_scale(ay, 5 * math.sin(2 * math.pi * k / 3)))) for k in range(3)]
        for k in range(3):
            _oriented_tri(thorns, ring[k], ring[(k + 1) % 3], tip, base)
    eyes = m.part('Eyes', (255, 230, 120))
    m_sphere(eyes, -8, 32, 20, 4, rings=2, segs=5); m_sphere(eyes, 8, 32, 20, 4, rings=2, segs=5)
    return m

def model_wisp():
    m = Model('PetalWisp')
    core = m.part('Core', (255, 235, 250))
    m_sphere(core, 0, 0, 0, 12, rings=3, segs=7)
    petals = m.part('Petals', (245, 150, 200))
    for k in range(6):
        ang = 2 * math.pi * k / 6
        tris = []
        m_petal(tris, 34, 11, 3, tilt=0.45)
        ca, sa = math.cos(ang), math.sin(ang)
        for (a, b, c) in tris:
            def R(p): return (p[0] * ca + p[2] * sa, p[1], -p[0] * sa + p[2] * ca)
            petals.append((R(a), R(b), R(c)))
    return m

def model_petal_shot():
    m = Model('PetalShot')
    p = m.part('Petal', (250, 170, 210))
    m_petal(p, 26, 9, 3, tilt=0.0)
    return m

def model_spike():
    m = Model('ThornSpike')
    p = m.part('Spike', (120, 70, 90))
    m_cone(p, 0, 0, 0, 14, 90, sides=6)
    return m

def model_plate():
    m = Model('Plate')
    base = m.part('Base', (150, 140, 160)); m_cyl(base, 0, 0, 0, 46, 6, sides=10)
    top = m.part('Top', (230, 150, 190)); m_cyl(top, 0, 6, 0, 34, 4, sides=10)
    return m

def model_pad():
    m = Model('PathPad')
    p = m.part('Pad', (255, 255, 255)); m_cyl(p, 0, 0, 0, 38, 8, sides=10)
    return m

def model_portal():
    m = Model('Portal')
    ring = m.part('Ring', (255, 200, 235))
    for k in range(10):
        ang = 2 * math.pi * k / 10
        tris = []
        m_petal(tris, 46, 12, 2, tilt=0.12)
        ca, sa = math.cos(ang), math.sin(ang)
        for (a, b, c) in tris:
            def R(p): return (p[0] * ca + (p[2] + 26) * sa, p[1], -p[0] * sa + (p[2] + 26) * ca)
            ring.append((R(a), R(b), R(c)))
    glow = m.part('Glow', (255, 240, 255)); m_cyl(glow, 0, 0, 0, 30, 2, sides=10)
    return m

def model_statue():
    m = Model('LilithStatue')
    robe = m.part('Robe', (235, 232, 245))
    m_cone(robe, 0, 0, 0, 40, 130, sides=10)
    m_sphere(robe, 0, 135, 0, 20, rings=3, segs=8, sy=0.9)
    head = m.part('Head', (245, 240, 250)); m_sphere(head, 0, 168, 0, 16, rings=3, segs=8)
    arms = m.part('Arms', (225, 222, 238))
    m_box(arms, -34, 96, 10, -20, 130, 30); m_box(arms, 20, 96, 10, 34, 130, 30)
    rose = m.part('Rose', (210, 40, 80)); m_sphere(rose, 0, 122, 34, 9, rings=2, segs=6)
    leaf = m.part('Leaf', (60, 130, 80)); m_cone(leaf, 0, 100, 32, 4, 24, sides=4)
    halo = m.part('Halo', (255, 235, 200))
    for k in range(8):
        a = 2 * math.pi * k / 8
        m_cone(halo, 34 * math.cos(a), 176, 34 * math.sin(a), 4, 16, sides=4)
    return m

def model_bramble():
    m = Model('Bramble')
    g = m.part('Vines', (60, 110, 60))
    rng = random.Random(9)
    for i in range(10):
        x = -110 + i * 24.5
        m_cyl(g, x, 0, rng.uniform(-8, 8), 13, rng.uniform(150, 215), sides=6, r_top=6)
    t = m.part('Thorns', (130, 70, 70))
    for i in range(16):
        x = rng.uniform(-110, 110); y = rng.uniform(30, 190)
        m_cone(t, x, y, 14, 4, 22, sides=4, apex_dz=8)
        m_cone(t, x, y, -14, 4, 22, sides=4, apex_dz=-8)
    return m

def model_barrier(variant):
    m = Model('Barrier%d' % variant)
    if variant == 0:
        a = m.part('Posts', (120, 90, 110))
        for i in range(7):
            x = -108 + i * 36
            m_cyl(a, x, 0, 0, 9, 270, sides=6, r_top=5)
        b = m.part('Thorns', (170, 80, 110))
        for i in range(14):
            x = -110 + i * 17
            m_cone(b, x, 30 + (i % 4) * 55, 8, 4, 26, sides=4, apex_dz=6)
            m_cone(b, x, 55 + (i % 3) * 60, -8, 4, 26, sides=4, apex_dz=-6)
        bar = m.part('Bars', (90, 70, 90)); m_box(bar, -120, 120, -6, 120, 132, 6); m_box(bar, -120, 240, -6, 120, 252, 6)
    else:
        a = m.part('Posts', (240, 238, 248))
        for i in range(7):
            x = -108 + i * 36
            m_cyl(a, x, 0, 0, 8, 292, sides=6, r_top=5)
        b = m.part('Roses', (235, 235, 245))
        for i in range(6):
            m_sphere(b, -90 + i * 36, 120 + (i % 2) * 70, 8, 15, rings=3, segs=6)
        r = m.part('Buds', (220, 60, 100))
        for i in range(6):
            m_sphere(r, -72 + i * 36, 210 - (i % 2) * 90, -8, 10, rings=2, segs=5)
        top = m.part('Arch', (250, 245, 252)); m_box(top, -120, 286, -10, 120, 300, 10)
    return m

def model_petal_ring():
    m = Model('PetalRing')
    p = m.part('Ring', (255, 190, 225))
    for k in range(16):
        ang = 2 * math.pi * k / 16
        tris = []
        m_petal(tris, 50, 14, 2, tilt=0.08)
        ca, sa = math.cos(ang), math.sin(ang)
        for (a, b, c) in tris:
            def R(pt): return (pt[0] * ca + (pt[2] + 40) * sa, pt[1], -pt[0] * sa + (pt[2] + 40) * ca)
            p.append((R(a), R(b), R(c)))
    return m

def model_warden():
    m = Model('Warden')
    body = m.part('Body', (130, 100, 70))
    m_cyl(body, 0, 70, 0, 50, 130, sides=10, r_top=38)
    m_box(body, -40, 0, -22, -8, 76, 22); m_box(body, 8, 0, -22, 40, 76, 22)
    head = m.part('Head', (170, 130, 90)); m_sphere(head, 0, 226, 0, 30, rings=3, segs=8)
    crown = m.part('Crown', (220, 70, 100))
    for k in range(7):
        a = 2 * math.pi * k / 7
        m_cone(crown, 26 * math.cos(a), 246, 26 * math.sin(a), 6, 38, sides=4)
    arms = m.part('Arms', (110, 85, 60))
    m_cyl(arms, -74, 90, 0, 18, 110, sides=8); m_cyl(arms, 74, 90, 0, 18, 110, sides=8)
    # the mace hangs straight down from its pivot (the shoulder) so the actor can swing it by rotating the part
    mace = m.part('Mace', (190, 175, 160))
    m_cyl(mace, 0, -104, 0, 7, 104, sides=6)
    m_sphere(mace, 0, -108, 0, 26, rings=3, segs=8)
    for k in range(8):
        a = 2 * math.pi * k / 8
        m_cone(mace, 30 * math.cos(a), -108, 30 * math.sin(a), 6, 22, sides=4, apex_dx=10 * math.cos(a), apex_dz=10 * math.sin(a))
    roots = m.part('Roots', (90, 130, 70))
    for k in range(6):
        a = 2 * math.pi * k / 6
        m_cone(roots, 54 * math.cos(a), 0, 54 * math.sin(a), 10, 50, sides=4, apex_dx=16 * math.cos(a), apex_dz=16 * math.sin(a))
    return m

def model_queen():
    m = Model('Queen')
    gown = m.part('Gown', (70, 25, 70))
    m_cone(gown, 0, 0, 0, 70, 200, sides=12)
    bust = m.part('Bust', (200, 170, 210)); m_sphere(bust, 0, 200, 0, 26, rings=3, segs=8, sy=1.1)
    head = m.part('Head', (235, 210, 225)); m_sphere(head, 0, 246, 0, 20, rings=3, segs=8)
    crown = m.part('Crown', (230, 40, 90))
    for k in range(9):
        a = 2 * math.pi * k / 9
        m_cone(crown, 18 * math.cos(a), 262, 18 * math.sin(a), 4, 32, sides=4, apex_dx=6 * math.cos(a), apex_dz=6 * math.sin(a))
    arms = m.part('Arms', (200, 165, 205))
    m_cyl(arms, -42, 150, 10, 9, 70, sides=6, r_top=6); m_cyl(arms, 42, 150, 10, 9, 70, sides=6, r_top=6)
    petals = m.part('Petals', (220, 50, 110))
    for k in range(8):
        ang = 2 * math.pi * k / 8
        tris = []
        m_petal(tris, 90, 24, 4, tilt=0.6)
        ca, sa = math.cos(ang), math.sin(ang)
        for (a, b, c) in tris:
            def R(pt): return (pt[0] * ca + (pt[2] + 30) * sa, pt[1] + 210, -pt[0] * sa + (pt[2] + 30) * ca)
            petals.append((R(a), R(b), R(c)))
    return m

MODEL_BUILDERS = [model_rose_knight, model_thornling, model_wisp, model_petal_shot, model_spike, model_plate, model_pad, model_portal,
                  model_statue, model_bramble, lambda: model_barrier(0), lambda: model_barrier(1), model_petal_ring, model_warden,
                  model_queen]

# dynamic collision for actors: (symbol, list of boxes (x0,y0,z0,x1,y1,z1))
def box_collision(name, boxes, light=0):
    col = Collision(name)
    surf = col.surface(light, SURFACE_STONE)
    for (x0, y0, z0, x1, y1, z1) in boxes:
        c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        ctr = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        for q in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3), (1, 2, 6, 5), (3, 7, 6, 2), (0, 1, 5, 4)]:
            pts = [c[i] for i in q]
            n = v_cross(v_sub(pts[1], pts[0]), v_sub(pts[2], pts[0]))
            mid = v_scale(v_add(v_add(pts[0], pts[1]), v_add(pts[2], pts[3])), 0.25)
            if v_dot(n, v_sub(mid, ctr)) < 0: pts = list(reversed(pts))
            col.tri(pts[0], pts[1], pts[2], surf); col.tri(pts[0], pts[2], pts[3], surf)
    return col

DYNA_COLLISIONS = [
    ('gLilBarrierCol', [(-120, 0, -16, 120, 290, 16)]),
    ('gLilBrambleCol', [(-120, 0, -20, 120, 220, 20)]),
    ('gLilPlateCol', [(-46, 0, -46, 46, 6, 46)]),
]

# ------------------------------------------------------------------------------------------------------- C emission
def c_header_comment(path_hint):
    return ('/* GENERATED by tools/gen_world.py - do not edit by hand. Regenerate with: python3 tools/gen_world.py */\n'
            '/* %s */\n' % path_hint)

def emit_textures(used):
    out = [c_header_comment('src/gen/lil_textures.c'), '#include "global.h"\n', '#include "lil_gen.h"\n\n']
    for name in used:
        data = texture_bytes(name)
        out.append('u64 gLilTex_%s[%d] = {\n' % (name, len(data) // 8))
        for i in range(0, len(data), 8):
            word = int.from_bytes(data[i:i + 8], 'big')
            out.append('    0x%016XULL,%s' % (word, '\n' if (i // 8) % 4 == 3 else ' '))
        out.append('};\n\n')
    return ''.join(out)

def gfx_for_groups(groups, vtx_name, textured, tex_for_mat, prim_for_mat=None, lit=False):
    """groups: list of (mat, tris) ; returns (vertex lines, gfx lines)."""
    vlines, glines = [], []
    vcount = 0
    for mat, tris in groups:
        if textured:
            glines.append('    gsDPPipeSync(),')
            glines.append('    gsDPLoadTextureBlock(gLilTex_%s, G_IM_FMT_IA, G_IM_SIZ_8b, 32, 32, 0, G_TX_WRAP | G_TX_NOMIRROR, '
                          'G_TX_WRAP | G_TX_NOMIRROR, 5, 5, G_TX_NOLOD, G_TX_NOLOD),' % tex_for_mat(mat))
        elif prim_for_mat is not None:
            r, g, b = prim_for_mat(mat)
            glines.append('    gsDPPipeSync(),')
            glines.append('    gsDPSetPrimColor(0, 0, %d, %d, %d, 255),' % (r, g, b))
        i = 0
        while i < len(tris):
            chunk = tris[i:i + 10]
            base = vcount
            for (pts, uvs, nrm_or_col) in chunk:
                for k in range(3):
                    p = pts[k]
                    s, t = uvs[k] if uvs else (0, 0)
                    c = nrm_or_col[k]
                    vlines.append('    { { { %d, %d, %d }, 0, { %d, %d }, { %d, %d, %d, 255 } } },' % (rnd(p[0]), rnd(p[1]), rnd(p[2]), s, t, c[0], c[1], c[2]))
                    vcount += 1
            n = len(chunk) * 3
            glines.append('    gsSPVertex(&%s[%d], %d, 0),' % (vtx_name, base, n))
            j = 0
            while j < len(chunk):
                if j + 1 < len(chunk):
                    glines.append('    gsSP2Triangles(%d, %d, %d, 0, %d, %d, %d, 0),' % (j * 3, j * 3 + 1, j * 3 + 2, j * 3 + 3, j * 3 + 4, j * 3 + 5))
                    j += 2
                else:
                    glines.append('    gsSP1Triangle(%d, %d, %d, 0),' % (j * 3, j * 3 + 1, j * 3 + 2))
                    j += 1
            i += 10
    return vlines, glines, vcount

def scene_opa_dl(sc):
    groups = []
    for mat, tris in sc.mesh.tris.items():
        groups.append((mat, [(pts, uvs, [sc._shade(mat, n, p) for p in pts]) for (pts, uvs, n, _fn) in tris]))
    return groups

def emit_scene_c(sc, idx, out):
    nm = sc.name
    groups = scene_opa_dl(sc)
    # vertices + display list
    used_tex = []
    def tex_for_mat(m):
        t = MATS[m][0]
        if t not in used_tex: used_tex.append(t)
        return t
    vlines, glines, vcount = gfx_for_groups(groups, 'sLil%sVtx' % nm, True, tex_for_mat)
    out.append('/* ------------------------------------------------ %s ------------------------------------------------ */\n' % nm)
    out.append('static Vtx sLil%sVtx[%d] = {\n%s\n};\n\n' % (nm, vcount, '\n'.join(vlines)))
    out.append('static Gfx sLil%sOpaDL[] = {\n'
               '    gsSPClearGeometryMode(G_LIGHTING),\n'
               '    gsSPTexture(0xFFFF, 0xFFFF, 0, G_TX_RENDERTILE, G_ON),\n%s\n'
               '    gsDPPipeSync(),\n    gsSPSetGeometryMode(G_LIGHTING),\n    gsSPEndDisplayList(),\n};\n\n' % (nm, '\n'.join(glines)))
    # collision
    verts, polys, surfaces, mn, mx = sc.col.finalize()
    out.append('static Vec3s sLil%sColVerts[%d] = {\n' % (nm, len(verts)))
    out.append(',\n'.join('    { %d, %d, %d }' % v for v in verts) + '\n};\n\n')
    out.append('static CollisionPoly sLil%sColPolys[%d] = {\n' % (nm, len(polys)))
    out.append(',\n'.join('    { %d, { %d, %d, %d }, { %d, %d, %d }, %d }' % (s, a, b, c, nx, ny, nz, d) for (s, a, b, c, nx, ny, nz, d) in polys) + '\n};\n\n')
    out.append('static SurfaceType sLil%sColSurfaces[%d] = {\n' % (nm, len(surfaces)))
    out.append(',\n'.join('    { { SURFACETYPE0(0, 0, 0, 0, 0, 0, 0, 0), SURFACETYPE1(%d, 0, %d, 0, 0, 0, 0, 0) } }' % (mat, light) for (light, mat) in surfaces) + '\n};\n\n')
    out.append('static BgCamInfo sLil%sBgCams[1] = { { %s, 0, NULL } };\n\n' % (nm, sc.cam))
    out.append('static CollisionHeader sLil%sCol = {\n    { %d, %d, %d }, { %d, %d, %d },\n    %d, sLil%sColVerts,\n    %d, sLil%sColPolys,\n'
               '    sLil%sColSurfaces, sLil%sBgCams,\n    0, NULL,\n};\n\n' % (nm, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2], len(verts), nm, len(polys), nm, nm, nm))
    # lights
    out.append('static EnvLightSettings sLil%sLights[%d] = {\n' % (nm, len(sc.lights)))
    for L in sc.lights:
        out.append('    { { %d, %d, %d }, { %d, %d, %d }, { %d, %d, %d }, { %d, %d, %d }, { %d, %d, %d }, { %d, %d, %d }, %d, %d },\n' % (
            *L['amb'], *L['l1d'], *L['l1c'], *L['l2d'], *L['l2c'], *L['fog'], ((L['blend'] // 4) << 10) | L['fog_near'], L['zfar']))
    out.append('};\n\n')
    # spawns + entrances
    out.append('static ActorEntry sLil%sPlayerSpawns[%d] = {\n' % (nm, len(sc.spawns)))
    for (x, y, z, yaw, mode) in sc.spawns:
        out.append('    { ACTOR_PLAYER, { %d, %d, %d }, { 0, (s16)SPAWN_ROT_FLAGS(%d, 0), 0 }, PLAYER_PARAMS(0xFF, %s) },\n' % (x, y, z, yaw, mode))
    out.append('};\n\n')
    out.append('static EntranceEntry sLil%sEntrances[%d] = {\n' % (nm, len(sc.spawns)))
    for i in range(len(sc.spawns)):
        out.append('    { %d, 0 },\n' % i)
    out.append('};\n\n')
    # the player cutscene chain (ocarina, item get, song warp ... cameras come from the scene's cutscene list)
    chain = ['CS_CAM_ID_GLOBAL_ITEM_OCARINA', 'CS_CAM_ID_GLOBAL_ITEM_GET', 'CS_CAM_ID_GLOBAL_ITEM_BOTTLE', 'CS_CAM_ID_GLOBAL_ITEM_SHOW',
             'CS_CAM_ID_GLOBAL_WARP_PAD_MOON', 'CS_CAM_ID_GLOBAL_MASK_TRANSFORMATION', 'CS_CAM_ID_GLOBAL_DEATH',
             'CS_CAM_ID_GLOBAL_REVIVE', 'CS_CAM_ID_GLOBAL_SONG_WARP', 'CS_CAM_ID_GLOBAL_WARP_PAD_ENTRANCE']
    hud = ['CS_HUD_VISIBILITY_ALL_ALT'] * 4 + ['CS_HUD_VISIBILITY_NONE'] * 6
    out.append('static CutsceneEntry sLil%sCutscenes[%d] = {\n' % (nm, len(chain)))
    for i, cam in enumerate(chain):
        nxt = str(i + 1) if i + 1 < len(chain) else 'CS_ID_NONE'
        out.append('    { 700, -1, %s, CS_SCRIPT_ID_NONE, %s, CS_END_SFX_NONE, 255, %s, CS_END_CAM_0, 0 },\n' % (cam, nxt, hud[i]))
    out.append('};\n\n')
    # room: object list, actors, mesh shape
    out.append('static s16 sLil%sRoomObjects[%d] = { %s };\n\n' % (nm, len(sc.objects), ', '.join(sc.objects)))
    out.append('static ActorEntry sLil%sRoomActors[] = {\n' % nm)
    n_actor = 0
    for (slot, x, y, z, yaw, params) in sorted(sc.actors, key=lambda a: (a[3], a[1], a[0])):
        out.append('    { LIL_ACTOR_ID(%s), { %d, %d, %d }, { 0, (s16)SPAWN_ROT_FLAGS(%d, 0x7F), 0 }, 0x%04X },\n' % (ACTOR_SLOT_NAMES[slot], x, y, z, yaw, params))
        n_actor += 1
    for (aid, x, y, z, yaw, params) in getattr(sc, 'actor_vanilla', []):
        out.append('    { %s, { %d, %d, %d }, { 0, (s16)SPAWN_ROT_FLAGS(%d, 0x7F), 0 }, 0x%04X },\n' % (aid, x, y, z, yaw, params))
        n_actor += 1
    out.append('};\n\n')
    out.append('static RoomShapeDListsEntry sLil%sRoomShapeEntries[1] = { { sLil%sOpaDL, NULL } };\n' % (nm, nm))
    out.append('static RoomShapeNormal sLil%sRoomShape = { { ROOM_SHAPE_TYPE_NORMAL }, 1, sLil%sRoomShapeEntries, sLil%sRoomShapeEntries + 1 };\n\n' % (nm, nm, nm))
    out.append('static SceneCmd sLil%sRoomHeader[] = {\n'
               '    SCENE_CMD_ROOM_BEHAVIOR(%s, 0, false, false, false, 0),\n'
               '    SCENE_CMD_SKYBOX_DISABLES(true, true),\n'
               '    SCENE_CMD_TIME_SETTINGS(255, 255, 0),\n'
               '    SCENE_CMD_ROOM_SHAPE(&sLil%sRoomShape),\n'
               '    SCENE_CMD_ECHO_SETTINGS(%d),\n'
               '    SCENE_CMD_OBJECT_LIST(%d, sLil%sRoomObjects),\n'
               '    SCENE_CMD_ACTOR_LIST(%d, sLil%sRoomActors),\n'
               '    SCENE_CMD_END(),\n};\n\n' % (nm, sc.room_type, nm, sc.echo, len(sc.objects), nm, n_actor, nm))
    out.append('static RomFile sLil%sRoomList[1] = { { 0, 0x10 } };\n' % nm)
    out.append('static SceneCmd* sLil%sRooms[1] = { sLil%sRoomHeader };\n\n' % (nm, nm))
    out.append('static SceneCmd sLil%sSceneHeader[] = {\n'
               '    SCENE_CMD_SOUND_SETTINGS(0, AMBIENCE_ID_DISABLED, %s),\n'
               '    SCENE_CMD_ROOM_LIST(1, sLil%sRoomList),\n'
               '    SCENE_CMD_ACTOR_CUTSCENE_LIST(%d, sLil%sCutscenes),\n'
               '    SCENE_CMD_COL_HEADER(&sLil%sCol),\n'
               '    SCENE_CMD_ENTRANCE_LIST(sLil%sEntrances),\n'
               '    SCENE_CMD_SPECIAL_FILES(NAVI_QUEST_HINTS_NONE, 0),\n'
               '    SCENE_CMD_SPAWN_LIST(%d, sLil%sPlayerSpawns),\n'
               '    SCENE_CMD_ENV_LIGHT_SETTINGS(%d, sLil%sLights),\n'
               '    SCENE_CMD_SKYBOX_SETTINGS(0, SKYBOX_NONE, 0, LIGHT_MODE_SETTINGS),\n'
               '    SCENE_CMD_SKYBOX_DISABLES(true, true),\n'
               '    SCENE_CMD_TIME_SETTINGS(255, 255, 0),\n'
               '    SCENE_CMD_END(),\n};\n\n' % (nm, sc.music, nm, len(chain), nm, nm, nm, len(sc.spawns), nm, len(sc.lights), nm))
    return used_tex, n_actor

def emit_world(scenes):
    out = [c_header_comment('src/gen/lil_world.c'),
           '#include "lilith.h"\n#include "command_macros_base.h" // CMD_PTR / CMD_W / CMD_BBBB used by the SCENE_CMD_* macros\n#include "lil_gen.h"\n\n']
    used_tex_all = []
    counts = []
    for i, sc in enumerate(scenes):
        used, n = emit_scene_c(sc, i, out)
        for t in used:
            if t not in used_tex_all: used_tex_all.append(t)
        counts.append(n)
    out.append('LilSceneDef gLilSceneDefs[%d] = {\n' % len(scenes))
    for sc in scenes:
        nm = sc.name
        ent = 'LIL_ENTR_SCENE_%s' % nm.upper()
        out.append('    { sLil%sSceneHeader, sLil%sRooms, 1, %s, %s, %d, "%s" },\n' % (nm, nm, sc.scene_const, ent, len(sc.spawns), nm))
    out.append('};\nconst s32 gLilNumSceneDefs = %d;\n\n' % len(scenes))
    out.append('LilActorList gLilActorLists[%d] = {\n' % len(scenes))
    for sc, n in zip(scenes, counts):
        out.append('    { sLil%sRoomActors, %d },\n' % (sc.name, n))
    out.append('};\nconst s32 gLilNumActorLists = %d;\n' % len(scenes))
    return ''.join(out), used_tex_all

def emit_models():
    out = [c_header_comment('src/gen/lil_models.c'), '#include "lilith.h"\n#include "lil_gen.h"\n\n']
    decls = []
    lines_h = []
    for builder in MODEL_BUILDERS:
        m = builder()
        for (pname, colour, tris) in m.parts:
            sym = 'gLil%s_%s' % (m.name, pname)
            groups = []
            entries = []
            for (a, b, c) in tris:
                n = v_norm(v_cross(v_sub(b, a), v_sub(c, a)))
                nb = tuple(int(clamp(rnd(x * 127), -127, 127)) & 0xFF for x in n)
                entries.append(((a, b, c), None, [nb, nb, nb]))
            groups.append((pname, entries))
            vlines, glines, vcount = gfx_for_groups(groups, sym + 'Vtx', False, None, prim_for_mat=lambda _m, col=colour: col, lit=True)
            out.append('static Vtx %sVtx[%d] = {\n%s\n};\n\n' % (sym, vcount, '\n'.join(vlines)))
            # models are drawn by the actors with their own combiner/geometry mode setup (lit, PRIMITIVE * SHADE)
            out.append('Gfx %sDL[] = {\n%s\n    gsSPEndDisplayList(),\n};\n\n' % (sym, '\n'.join(glines)))
            lines_h.append('extern Gfx %sDL[];' % sym)
    for (sym, boxes) in DYNA_COLLISIONS:
        col = box_collision(sym, boxes)
        verts, polys, surfaces, mn, mx = col.finalize()
        out.append('static Vec3s %sVerts[%d] = {\n%s\n};\n\n' % (sym, len(verts), ',\n'.join('    { %d, %d, %d }' % v for v in verts)))
        out.append('static CollisionPoly %sPolys[%d] = {\n%s\n};\n\n' % (sym, len(polys), ',\n'.join(
            '    { %d, { %d, %d, %d }, { %d, %d, %d }, %d }' % (s, a, b, c, nx, ny, nz, d) for (s, a, b, c, nx, ny, nz, d) in polys)))
        out.append('static SurfaceType %sSurfaces[1] = { { { SURFACETYPE0(0, 0, 0, 0, 0, 0, 0, 0), SURFACETYPE1(2, 0, 0, 0, 0, 0, 0, 0) } } };\n' % sym)
        out.append('CollisionHeader %s = { { %d, %d, %d }, { %d, %d, %d }, %d, %sVerts, %d, %sPolys, %sSurfaces, NULL, 0, NULL };\n\n' % (
            sym, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2], len(verts), sym, len(polys), sym, sym))
        lines_h.append('extern CollisionHeader %s;' % sym)
    return ''.join(out), lines_h

def emit_header(used_tex, model_decls, scenes):
    out = ['/* GENERATED by tools/gen_world.py - do not edit by hand. */\n#ifndef LIL_GEN_H\n#define LIL_GEN_H\n\n#include "global.h"\n\n']
    for t in used_tex:
        out.append('extern u64 gLilTex_%s[128];\n' % t)
    out.append('\n')
    out.extend(l + '\n' for l in model_decls)
    out.append('\n// Switch flags used by the placed actors (see tools/gen_world.py)\n')
    for n, v in (('LIL_FLAG_SANCTUARY_GATE', FLAG_SANCTUARY_GATE), ('LIL_FLAG_ENTRY_PLATE', FLAG_ENTRY_PLATE),
                 ('LIL_FLAG_GALLERY_CLEAR', FLAG_GALLERY_CLEAR), ('LIL_FLAG_PATH_SOLVED', FLAG_PATH_SOLVED),
                 ('LIL_FLAG_KNIGHTS_CLEAR', FLAG_KNIGHTS_CLEAR), ('LIL_FLAG_WARDEN_DEAD', FLAG_WARDEN_DEAD),
                 ('LIL_FLAG_QUEEN_DEAD', FLAG_QUEEN_DEAD)):
        out.append('#define %s 0x%02X\n' % (n, v))
    out.append('\n#define LIL_PORTAL_TO_CRYPT %d\n#define LIL_PORTAL_TO_SANCTUARY %d\n#define LIL_PORTAL_HOME %d\n' % (PORTAL_TO_CRYPT, PORTAL_TO_SANCTUARY, PORTAL_HOME))
    out.append('#define LIL_BARRIER_CRYPT %d\n#define LIL_BARRIER_SANCTUARY %d\n' % (BARRIER_CRYPT, BARRIER_SANCTUARY))
    out.append('\n#endif\n')
    return ''.join(out)

# --------------------------------------------------------------------------------------------------- validation
def check_scene(sc):
    """Structural sanity checks on the generated collision/spawn data. Returns a list of problem strings."""
    problems = []
    verts, polys, surfaces, mn, mx = sc.col.finalize()
    if len(verts) > 8000: problems.append('%s: too many collision vertices (%d)' % (sc.name, len(verts)))
    if len(polys) > 65000: problems.append('%s: too many collision polys' % sc.name)
    for (s, a, b, c, nx, ny, nz, d) in polys:
        if not (0 <= a < len(verts) and 0 <= b < len(verts) and 0 <= c < len(verts)): problems.append('bad vertex index')
        mag = math.sqrt(nx * nx + ny * ny + nz * nz) / 0x7FFF
        if abs(mag - 1.0) > 0.01: problems.append('%s: poly normal not unit (%.3f)' % (sc.name, mag))
        if s >= len(surfaces): problems.append('bad surface index')
    # every spawn must have a floor poly below it: nearest floor poly by vertical ray test
    def floor_below(x, y, z):
        best = None
        for (s, a, b, c, nx, ny, nz, d) in polys:
            if ny < 0x4000: continue
            A, B, C = verts[a], verts[b], verts[c]
            # barycentric in xz
            den = (B[2] - C[2]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[2] - C[2])
            if den == 0: continue
            w1 = ((B[2] - C[2]) * (x - C[0]) + (C[0] - B[0]) * (z - C[2])) / den
            w2 = ((C[2] - A[2]) * (x - C[0]) + (A[0] - C[0]) * (z - C[2])) / den
            w3 = 1 - w1 - w2
            if min(w1, w2, w3) < -1e-6: continue
            h = w1 * A[1] + w2 * B[1] + w3 * C[1]
            if h <= y + 40 and (best is None or h > best): best = h
        return best
    for (x, y, z, yaw, mode) in sc.spawns:
        h = floor_below(x, y + 10, z)
        if h is None: problems.append('%s: spawn (%d,%d,%d) has no floor below it' % (sc.name, x, y, z))
        elif abs(h - y) > 12: problems.append('%s: spawn (%d,%d,%d) floats/sinks relative to floor %.1f' % (sc.name, x, y, z, h))
    for (slot, x, y, z, yaw, params) in sc.actors:
        h = floor_below(x, y + 10, z)
        if h is None and slot not in (A_BARRIER,): problems.append('%s: actor slot %d at (%d,%d,%d) has no floor' % (sc.name, slot, x, y, z))
    return problems

def generate(check_only=False):
    sanctuary, crypt = build_sanctuary(), build_crypt()
    scenes = [sanctuary, crypt]
    problems = []
    for sc in scenes:
        problems += check_scene(sc)
        verts, polys, surfaces, mn, mx = sc.col.finalize()
        tris = sum(len(t) for t in sc.mesh.tris.values())
        print('%-10s render tris: %5d   collision: %5d polys %5d verts   bounds %s..%s   actors: %d' % (
            sc.name, tris, len(polys), len(verts), mn, mx, len(sc.actors) + len(getattr(sc, 'actor_vanilla', []))))
    if problems:
        print('PROBLEMS:'); [print('  -', p) for p in problems]
        return 1
    print('layout checks passed')
    if check_only:
        return 0
    world_c, used_tex = emit_world(scenes)
    models_c, model_decls = emit_models()
    os.makedirs(GEN_DIR, exist_ok=True)
    with open(os.path.join(GEN_DIR, 'lil_textures.c'), 'w') as f: f.write(emit_textures(used_tex))
    with open(os.path.join(GEN_DIR, 'lil_world.c'), 'w') as f: f.write(world_c)
    with open(os.path.join(GEN_DIR, 'lil_models.c'), 'w') as f: f.write(models_c)
    with open(os.path.join(INC_DIR, 'lil_gen.h'), 'w') as f: f.write(emit_header(used_tex, model_decls, scenes))
    print('wrote src/gen/lil_textures.c, src/gen/lil_world.c, src/gen/lil_models.c, include/lil_gen.h')
    return 0

if __name__ == '__main__':
    sys.exit(generate(check_only='--check' in sys.argv))
