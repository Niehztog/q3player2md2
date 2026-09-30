"""Render written MD2 files to a contact sheet, as a visual check.

Everything is read back from disk: the MD2 through md2.read, the PCX skin
through a decoder that walks the data the way id's LoadPCX does, colours
through the Q2 palette. Shading uses the stored MD2 normals, texturing the
integer texture coordinates (what q2pro and the software renderer use).
Triangles seen from behind are drawn magenta, so inside-out geometry or holes
show up. The grey box is Q2's player bounding box, the line the floor.
"""

import os

import numpy as np
from PIL import Image, ImageDraw

from . import images, md2
from .anorms import ANORMS

SHOW = ['stand01', 'stand20', 'run1', 'run4', 'attack1', 'attack3', 'pain101', 'pain201',
        'pain301', 'jump1', 'jump2', 'jump4', 'flip06', 'salute06', 'taunt08', 'wave06',
        'point06', 'crstnd01', 'crwalk3', 'crattak1', 'crpain1', 'crdeath5', 'death106',
        'death206', 'death308']

CELL_W, CELL_H = 200, 240
PX = 2.6                    # pixels per unit
FLOOR = -24


def read_pcx(data):
    """id's LoadPCX, in Python: decode exactly xmax+1 bytes per row."""
    xmax, ymax = int.from_bytes(data[8:10], 'little'), int.from_bytes(data[10:12], 'little')
    w, h = xmax + 1, ymax + 1
    out = np.zeros((h, w), np.uint8)
    raw = memoryview(data)[128:]
    p = 0
    for y in range(h):
        x = 0
        row = out[y]
        while x < w:
            b = raw[p]
            p += 1
            if (b & 0xc0) == 0xc0:
                run = b & 0x3f
                b = raw[p]
                p += 1
            else:
                run = 1
            row[x:x + run] = b
            x += run
    return out


def _yaw_matrix(yaw_deg):
    a = np.radians(yaw_deg)
    c, s = np.cos(a), np.sin(a)
    # rotate the world so the camera looks along -X from +X
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]], np.float32)


def render(meshes, yaw, w=CELL_W, h=CELL_H, px=PX):
    """meshes: [(xyz (V,3), normals (V,3), tris_xyz, tris_st, st, texture RGBA, skin w, skin h)]

    Front faces first, alpha-tested like id's GL renderer (index 255 is cut
    out); then back faces, drawn magenta only where nothing is in front of them.
    """
    color = np.full((h, w, 3), 40, np.uint8)
    zbuf = np.full((h, w), -1e9, np.float32)
    rot = _yaw_matrix(yaw)
    light = rot.T @ np.array([0.6, 0.3, 0.75], np.float32)
    light /= np.linalg.norm(light)
    cx, cy = w / 2, h - 14 + FLOOR * px
    magenta = np.array([255, 0, 255], np.uint8)
    for back_pass in (False, True):
        for xyz, nrm, tx, ts, st, tex, sw, sh in meshes:
            v = xyz @ rot.T
            sx = cx + v[:, 1] * px
            sy = cy - v[:, 2] * px
            depth = v[:, 0]
            shade = 0.35 + 0.65 * np.clip(nrm @ light, 0, 1)
            th, tw = tex.shape[:2]
            for (a, b, c), (sa, sb, sc) in zip(tx, ts):
                xs = np.array([sx[a], sx[b], sx[c]])
                ys = np.array([sy[a], sy[b], sy[c]])
                den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
                # MD2 triangles are clockwise seen from outside: den > 0 faces the camera
                if abs(den) < 1e-9 or (den > 0) == back_pass:
                    continue
                x0, x1 = int(max(np.floor(xs.min()), 0)), int(min(np.ceil(xs.max()), w - 1))
                y0, y1 = int(max(np.floor(ys.min()), 0)), int(min(np.ceil(ys.max()), h - 1))
                if x0 > x1 or y0 > y1:
                    continue
                gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
                l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
                l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
                l2 = 1 - l0 - l1
                inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
                if not inside.any():
                    continue
                z = l0 * depth[a] + l1 * depth[b] + l2 * depth[c]
                sub = zbuf[y0:y1 + 1, x0:x1 + 1]
                region = color[y0:y1 + 1, x0:x1 + 1]
                u = (l0 * st[sa, 0] + l1 * st[sb, 0] + l2 * st[sc, 0]) / sw
                t = (l0 * st[sa, 1] + l1 * st[sb, 1] + l2 * st[sc, 1]) / sh
                texel = tex[np.clip((t * th).astype(int), 0, th - 1), np.clip((u * tw).astype(int), 0, tw - 1)]
                if back_pass:
                    vis = inside & (z > sub + 0.5) & (texel[..., 3] > 0)
                    sub[vis] = z[vis]
                    region[vis] = magenta
                    continue
                vis = inside & (z > sub) & (texel[..., 3] > 0)
                if not vis.any():
                    continue
                sub[vis] = z[vis]
                lit = l0 * shade[a] + l1 * shade[b] + l2 * shade[c]
                pix = (texel[..., :3].astype(np.float32) * lit[..., None]).clip(0, 255).astype(np.uint8)
                region[vis] = pix[vis]
    return color


def _box_and_floor(img, yaw):
    d = ImageDraw.Draw(img)
    cx, cy = CELL_W / 2, CELL_H - 14 + FLOOR * PX
    d.line([(0, cy - FLOOR * PX), (CELL_W, cy - FLOOR * PX)], fill=(90, 90, 90))
    half = 16 * (abs(np.cos(np.radians(yaw))) + abs(np.sin(np.radians(yaw))))
    d.rectangle([cx - half * PX, cy - 32 * PX, cx + half * PX, cy + 24 * PX], outline=(80, 80, 80))


def _load(path, q2, palette):
    with open(path, 'rb') as f:
        m = md2.read(f.read())
    skin_dir = os.path.dirname(path)
    tex = None
    if os.path.basename(path) == 'tris.md2':
        with open(os.path.join(skin_dir, 'default.pcx'), 'rb') as f:
            tex = images.palette_to_rgba(read_pcx(f.read()), palette)
    elif m.skins and q2.exists(m.skins[0]):
        tex = images.palette_to_rgba(read_pcx(q2.read(m.skins[0])), palette)
    if tex is None:
        tex = np.full((8, 8, 4), 200, np.uint8)
    return m, tex


def contact_sheet(model_dir, q2, outdir, weapon='weapon.md2'):
    palette = images.load_palette(q2)
    body, body_tex = _load(os.path.join(model_dir, 'tris.md2'), q2, palette)
    wpath = os.path.join(model_dir, weapon)
    gun, gun_tex = _load(wpath, q2, palette) if os.path.exists(wpath) else (None, None)
    names = [f.name for f in body.frames]
    cols = 5
    rows = (len(SHOW) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * CELL_W * 2, rows * CELL_H), (20, 20, 20))
    for k, fname in enumerate(SHOW):
        i = names.index(fname)
        meshes = []
        for m, tex in ((body, body_tex), (gun, gun_tex)):
            if m is None or i >= len(m.frames):
                continue
            fr = m.frames[i]
            meshes.append((fr.xyz.astype(np.float32), ANORMS[fr.normal_idx], m.tris_xyz, m.tris_st,
                           m.st, tex, m.skinwidth, m.skinheight))
        for j, yaw in enumerate((0, 45)):
            img = Image.fromarray(render(meshes, yaw))
            _box_and_floor(img, yaw)
            ImageDraw.Draw(img).text((4, 3), '%s %s' % (fname, 'front' if yaw == 0 else '3/4'),
                                     fill=(230, 230, 120))
            sheet.paste(img, ((k % cols) * 2 * CELL_W + j * CELL_W, (k // cols) * CELL_H))
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, os.path.basename(model_dir.rstrip('/')) + '.png')
    sheet.save(out)
    return out


def closeup(model_dir, q2, out, frame='stand01', yaws=(0, 90, 180, 270), weapon='weapon.md2', px=6):
    """One frame from several sides, large."""
    palette = images.load_palette(q2)
    body, body_tex = _load(os.path.join(model_dir, 'tris.md2'), q2, palette)
    wpath = os.path.join(model_dir, weapon)
    gun, gun_tex = _load(wpath, q2, palette) if weapon and os.path.exists(wpath) else (None, None)
    i = [f.name for f in body.frames].index(frame)
    meshes = []
    for m, tex in ((body, body_tex), (gun, gun_tex)):
        if m is not None and i < len(m.frames):
            fr = m.frames[i]
            meshes.append((fr.xyz.astype(np.float32), ANORMS[fr.normal_idx], m.tris_xyz, m.tris_st,
                           m.st, tex, m.skinwidth, m.skinheight))
    w, h = int(80 * px), int(76 * px)
    sheet = Image.new('RGB', (w * len(yaws), h))
    for k, yaw in enumerate(yaws):
        sheet.paste(Image.fromarray(render(meshes, yaw, w, h, px)), (k * w, 0))
    sheet.save(out)
    return out
