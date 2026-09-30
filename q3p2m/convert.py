"""Convert one Quake III player model into a Quake II player model directory."""

import os
import re

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


def _icon(q3, variant, atlas, rgba_atlas):
    path = next(filter(None, (q3.find(p, ('.tga', '.jpg', '.png')) for p in variant.icons)), None)
    if path:
        img = images.load_image(q3.read(path))
    else:
        img = atlas.head_region(rgba_atlas)
    return np.asarray(Image.fromarray(img, 'RGBA').resize((32, 32), Image.LANCZOS)), path is not None


def _head(q3, model_dir, model, head):
    """Directory and file of the head: the model's own head.md3, else a Team
    Arena head, models/players/heads/<head>/<head>.md3, which is also where Q3
    looks for a model without a head of its own (CG_RegisterClientModelname)."""
    if head is None and q3.exists(model_dir + 'head.md3'):
        return model_dir, model_dir + 'head.md3'
    head = head or model
    head_dir = 'models/players/heads/%s/' % head
    return head_dir, head_dir + head + '.md3'


def team_arena_characters(q3):
    """Team Arena's characters from teaminfo.txt: name -> (body model, head).
    The body is James's for "male", Janet's for "female", else the model the
    entry names (ui_main.c Character_Parse); the head has the character's name."""
    if not q3.exists('teaminfo.txt'):
        return {}
    text = q3.read('teaminfo.txt').decode('latin1')
    block = re.search(r'\bcharacters\s*\{((?:\s*\{[^{}]*\})*)\s*\}', text)
    out = {}
    for name, sex in re.findall(r'\{\s*"([^"]+)"\s+"([^"]+)"', block.group(1) if block else ''):
        body = {'male': 'james', 'female': 'janet'}.get(sex.lower(), sex.lower())
        out[name.lower()] = (body, name.lower())
    return out


def convert(q3, q2, model, outdir, name=None, scale=0.9, vwep=True, with_sounds=True, head=None):
    r = Result()
    name = name or model
    model_dir = 'models/players/%s/' % model
    head_dir, head_md3 = _head(q3, model_dir, model, head)
    dirs = {'lower': model_dir, 'upper': model_dir, 'head': head_dir}
    parts = {}
    for p in skins.PARTS:
        path = head_md3 if p == 'head' else model_dir + p + '.md3'
        if not q3.exists(path):
            raise FileNotFoundError('not found: %s' % path)
        parts[p] = bake.Part(md3.load(q3.read(path), '%s/%s' % (model, p)))
    cfg = animcfg.parse(q3.read(model_dir + 'animation.cfg').decode('latin1'), model_dir + 'animation.cfg')
    variants = skins.find_variants(q3, dirs)
    if not variants:
        raise ValueError('%s: no complete set of lower/upper/head .skin files' % model)

    skinset = skins.SkinSet(q3, dirs, parts, variants)
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
        icon, had_icon = _icon(q3, variant, atlas, rgba)
        if not had_icon:
            r.warn('%s: no icon, used the head texture' % variant.name)
        icon_idx = quantize(icon, alpha_cutout=True)
        for skin in [variant.name] + ([TEAM_ALIASES[variant.name]] if variant.name in TEAM_ALIASES else []):
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
        ', '.join(v.name for v in variants)))
    if skinset.left_out:
        r.info('left out, Q3 only adds their light: %s'
               % ', '.join('%s/%s (%s)' % e for e in skinset.left_out))
    for (part, surf), where in skinset.hidden.items():
        r.info('%s/%s hidden in %s, where Q3 only adds its light' % (part, surf, ', '.join(where)))
    if skinset.kept:
        r.info('drawn solid, although Q3 only adds their light: %s'
               % ', '.join('%s/%s' % k for k in skinset.kept))
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
