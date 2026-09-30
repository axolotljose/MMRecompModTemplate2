#!/usr/bin/env python3
"""
Software preview of the generated world (no game needed). Renders the two scenes and the actor models to PNG so the layout
and the models can be eyeballed, and so regressions in the generator are easy to spot.

    pip install matplotlib numpy
    python3 tools/preview.py            # writes docs/previews/*.png

This only reads the generator's in-memory geometry; it is purely a development aid.
"""
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

sys.path.insert(0, os.path.dirname(__file__))
import gen_world as gw

OUT = os.path.join(gw.ROOT, 'docs', 'previews')

def scene_polys(sc, cull_ceiling=True):
    polys, colors = [], []
    for mat, tris in sc.mesh.tris.items():
        for (pts, uvs, n, _fn) in tris:
            if cull_ceiling and n[1] < -0.5:
                continue                         # skip ceilings so the inside is visible from above
            c = [sc._shade(mat, n, p) for p in pts]
            col = tuple(sum(ch[i] for ch in c) / 3.0 / 255.0 for i in range(3))
            polys.append([(p[0], p[2], p[1]) for p in pts])   # x, z, y so that "up" is vertical in the plot
            colors.append(col)
    return polys, colors

def actor_markers(sc, ax):
    names = {0: 'statue', 1: 'portal', 2: 'gate', 3: 'plate', 4: 'path', 5: 'bramble', 6: 'arena', 7: 'thornling', 8: 'wisp',
             9: 'knight', 10: 'hazard', 11: 'WARDEN', 12: 'QUEEN'}
    marks = {0: ('*', 'gold'), 1: ('o', 'magenta'), 2: ('s', 'red'), 3: ('D', 'orange'), 4: ('P', 'cyan'), 5: ('x', 'green'),
             6: ('h', 'white'), 7: ('^', 'lime'), 8: ('v', 'pink'), 9: ('p', 'blue'), 11: ('X', 'brown'), 12: ('X', 'purple')}
    for (slot, x, y, z, yaw, params) in sc.actors:
        if slot in marks:
            m, c = marks[slot]
            ax.plot([x], [z], marker=m, color=c, markersize=8, markeredgecolor='black', linestyle='none')
    for (x, y, z, yaw, mode) in sc.spawns:
        ax.plot([x], [z], marker='>', color='white', markersize=9, markeredgecolor='black', linestyle='none')

def render_topdown(sc, path, xlim=None, zlim=None, size=(9, 9)):
    polys, colors = scene_polys(sc)
    fig, ax = plt.subplots(figsize=size, dpi=110)
    ax.set_facecolor('#101018')
    # painter's algorithm: lowest first so taller things are drawn over the floor
    order = sorted(range(len(polys)), key=lambda i: sum(p[2] for p in polys[i]) / 3)
    from matplotlib.patches import Polygon
    for i in order:
        ax.add_patch(Polygon([(p[0], p[1]) for p in polys[i]], closed=True, facecolor=colors[i], edgecolor='none'))
    actor_markers(sc, ax)
    ax.set_aspect('equal'); ax.invert_yaxis()
    if xlim: ax.set_xlim(*xlim)
    if zlim: ax.set_ylim(zlim[1], zlim[0])
    ax.set_title('%s (top down, x east / z south)' % sc.name)
    fig.savefig(path, bbox_inches='tight'); plt.close(fig)

def render_3d(sc, path, elev=38, azim=-60, xlim=None, zlim=None, ylim=(0, 500), size=(10, 8)):
    polys, colors = scene_polys(sc)
    fig = plt.figure(figsize=size, dpi=110)
    ax = fig.add_subplot(111, projection='3d')
    ax.add_collection3d(Poly3DCollection(polys, facecolors=colors, edgecolors='none'))
    allp = np.array([p for poly in polys for p in poly])
    xl = xlim or (allp[:, 0].min(), allp[:, 0].max()); zl = zlim or (allp[:, 1].min(), allp[:, 1].max())
    ax.set_xlim(*xl); ax.set_ylim(*zl); ax.set_zlim(*ylim)
    ax.set_box_aspect((xl[1] - xl[0], zl[1] - zl[0], (ylim[1] - ylim[0]) * 1.0))
    ax.view_init(elev=elev, azim=azim); ax.set_axis_off(); ax.set_facecolor('#101018')
    fig.savefig(path, bbox_inches='tight', facecolor='#101018'); plt.close(fig)

def render_models(path):
    builders = [gw.model_rose_knight, gw.model_thornling, gw.model_wisp, gw.model_statue, gw.model_warden, gw.model_queen,
                gw.model_portal, gw.model_bramble, lambda: gw.model_barrier(0), lambda: gw.model_barrier(1), gw.model_plate, gw.model_spike]
    n = len(builders)
    cols = 4
    rows = int(math.ceil(n / cols))
    fig = plt.figure(figsize=(cols * 3.4, rows * 3.6), dpi=100)
    light = gw.v_norm((0.4, 0.9, 0.6))
    for idx, b in enumerate(builders):
        m = b()
        ax = fig.add_subplot(rows, cols, idx + 1, projection='3d')
        allpts = []
        for (pname, colour, tris) in m.parts:
            polys, cols_ = [], []
            for (a_, b_, c_) in tris:
                nrm = gw.v_norm(gw.v_cross(gw.v_sub(b_, a_), gw.v_sub(c_, a_)))
                s = 0.45 + 0.55 * max(0.0, gw.v_dot(nrm, light))
                polys.append([(p[0], p[2], p[1]) for p in (a_, b_, c_)])
                cols_.append(tuple(min(1.0, ch / 255.0 * s) for ch in colour))
                allpts += [(p[0], p[2], p[1]) for p in (a_, b_, c_)]
            ax.add_collection3d(Poly3DCollection(polys, facecolors=cols_, edgecolors='none'))
        pts = np.array(allpts)
        mid = (pts.max(axis=0) + pts.min(axis=0)) / 2
        span = max((pts.max(axis=0) - pts.min(axis=0))) / 2 * 1.05
        ax.set_xlim(mid[0] - span, mid[0] + span); ax.set_ylim(mid[1] - span, mid[1] + span); ax.set_zlim(mid[2] - span, mid[2] + span)
        ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=14, azim=-35); ax.set_axis_off()
        ax.set_title(m.name, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, bbox_inches='tight'); plt.close(fig)

def main():
    os.makedirs(OUT, exist_ok=True)
    sanctuary, crypt = gw.build_sanctuary(), gw.build_crypt()
    render_topdown(sanctuary, os.path.join(OUT, 'sanctuary_top.png'), size=(8, 10))
    render_3d(sanctuary, os.path.join(OUT, 'sanctuary_3d.png'), elev=42, azim=-55, ylim=(0, 700), size=(9, 9))
    render_topdown(crypt, os.path.join(OUT, 'crypt_top.png'), size=(6, 16))
    render_3d(crypt, os.path.join(OUT, 'crypt_3d_entry.png'), elev=50, azim=-70, xlim=(-500, 500), zlim=(-2000, 450), ylim=(0, 500), size=(9, 9))
    render_3d(crypt, os.path.join(OUT, 'crypt_3d_boss.png'), elev=50, azim=-70, xlim=(-800, 800), zlim=(-7700, -4700), ylim=(0, 700), size=(9, 9))
    render_models(os.path.join(OUT, 'models.png'))
    print('wrote previews to', OUT)

if __name__ == '__main__':
    main()
