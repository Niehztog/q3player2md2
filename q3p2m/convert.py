"""Convert one Quake III player model into a Quake II player model directory."""

import os

import numpy as np
from PIL import Image

from . import animcfg, bake, images, md2, md3, mesh, skins, sounds, weapons

# Q2 CTF forces these skin names on its teams
TEAM_ALIASES = {'red': 'ctf_r', 'blue': 'ctf_b'}

_QUANTIZERS = {}    # palette bytes -> Quantizer; building the lookup table takes a moment


class Result:
    def __init__(self):
        self.lines = []
        self.warnings = []
        self.problems = []

    def info(self, msg):
        self.lines.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def _collapse(warnings):
    """'variant part/surface: message' lines -> one line per variant and message."""
    grouped = {}
    for w in warnings:
        head, _, msg = w.partition(': ')
        variant, _, where = head.partition(' ')
        grouped.setdefault((variant, msg), []).append(where)
    return ['%s %s: %s' % (v, ', '.join(where), msg) for (v, msg), where in grouped.items()]


def _icon(q3, model_dir, variant, atlas, rgba_atlas):
    path = q3.find('%sicon_%s.tga' % (model_dir, variant), ('.tga', '.jpg', '.png'))
    if path:
        img = images.load_image(q3.read(path))
    else:
        img = atlas.head_region(rgba_atlas)
    return np.asarray(Image.fromarray(img, 'RGBA').resize((32, 32), Image.LANCZOS)), path is not None


def convert(q3, q2, model, outdir, name=None, scale=0.9, vwep=True, with_sounds=True):
    r = Result()
    name = name or model
    model_dir = 'models/players/%s/' % model
    parts = {}
    for p in skins.PARTS:
        path = model_dir + p + '.md3'
        if not q3.exists(path):
            raise FileNotFoundError('not found: %s' % path)
        parts[p] = bake.Part(md3.load(q3.read(path), '%s/%s' % (model, p)))
    cfg = animcfg.parse(q3.read(model_dir + 'animation.cfg').decode('latin1'), model_dir + 'animation.cfg')
    variants = skins.find_variants(q3, model_dir)
    if not variants:
        raise ValueError('%s: no complete set of lower/upper/head .skin files' % model)

    skinset = skins.SkinSet(q3, model_dir, parts, variants)
    for w in _collapse(skinset.warnings):
        r.warn(w)
    atlas = skins.Atlas(skinset, parts)
    baked = bake.bake(parts, cfg, scale)
    body = mesh.Mesh(parts, skinset, atlas)

    out = os.path.join(outdir, 'players', name)
    os.makedirs(out, exist_ok=True)

    palette = images.load_palette(q2)
    key = palette.tobytes()
    if key not in _QUANTIZERS:
        _QUANTIZERS[key] = images.Quantizer(palette)
    quantize = _QUANTIZERS[key]
    skin_paths = []
    for vi, variant in enumerate(variants):
        cutout = atlas.uses_alpha(vi)
        rgba = atlas.render(vi)
        indices = quantize(rgba, alpha_cutout=cutout)
        hires = atlas.render(vi, atlas.hires) if atlas.hires > 1 else rgba
        icon, had_icon = _icon(q3, model_dir, variant, atlas, rgba)
        if not had_icon:
            r.warn('%s: no icon_%s, used the head texture' % (variant, variant))
        icon_idx = quantize(icon, alpha_cutout=True)
        for skin in [variant] + ([TEAM_ALIASES[variant]] if variant in TEAM_ALIASES else []):
            images.write_pcx(os.path.join(out, skin + '.pcx'), indices, palette)
            images.write_tga(os.path.join(out, skin + '.tga'), hires, cutout)
            images.write_pcx(os.path.join(out, skin + '_i.pcx'), icon_idx, palette)
            images.write_tga(os.path.join(out, skin + '_i.tga'), icon, True)
            skin_paths.append('players/%s/%s.pcx' % (name, skin))

    model2 = body.md2(baked, atlas.width, atlas.height, skin_paths[:md2.MAX_SKINS])
    commands = md2.write(model2, os.path.join(out, 'tris.md2'))
    r.info('tris.md2: %d vertices (%d before welding), %d triangles, %d GL commands, 198 frames'
           % (body.num_xyz, sum(p.xyz.shape[1] for p in parts.values()), len(body.tris_xyz), commands))
    r.info('skin: %dx%d PCX%s; variants: %s' % (
        atlas.width, atlas.height,
        '' if atlas.hires == 1 else ' (scaled to %.0f%%, TGA at %dx)' % (atlas.scale * 100, atlas.hires),
        ', '.join(variants)))
    if body.dropped:
        r.info('dropped %d degenerate triangles' % body.dropped)
    if body.doubled:
        r.info('%d triangles made two-sided (Q3 shader has cull disable)' % body.doubled)

    if 'tag_weapon' not in parts['upper'].model.tags:
        r.warn('upper.md3 has no tag_weapon; weapons are held at the torso')
    written = []
    for wname, (src, wscale, offset) in weapons.WEAPONS.items():
        if not vwep and wname != 'weapon.md2':
            continue
        if not q2.exists(src):
            continue
        wmodel = weapons.build(md2.read(q2.read(src)), wscale, offset, baked)
        md2.write(wmodel, os.path.join(out, wname))
        written.append(wname)
    if 'weapon.md2' not in written:
        md2.write(weapons.placeholder(baked), os.path.join(out, 'weapon.md2'))
        r.warn('no Q2 shotgun model found; wrote an invisible weapon.md2')
        written.insert(0, 'weapon.md2 (placeholder)')
    r.info('weapons: %s' % ', '.join(written))

    if with_sounds:
        n, missing = sounds.copy(q3, model, cfg.sex, out)
        r.info('sounds: %d copied%s' % (n, (', missing ' + ', '.join(missing)) if missing else ''))

    for fname in sorted(os.listdir(out)):
        if fname.endswith('.md2'):
            with open(os.path.join(out, fname), 'rb') as f:
                for p in md2.validate(f.read()):
                    r.problems.append('%s: %s' % (fname, p))
    r.out = out
    return r
