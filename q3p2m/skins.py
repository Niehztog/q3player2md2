"""Q3 .skin files -> one Q2 skin atlas per skin variant.

An MD2 has a single set of texture coordinates, so every variant (default,
red, blue, ...) must use the same atlas layout. Surfaces that show the same
image in every variant share a region ("slot"); each slot covers the part of
its image the surfaces actually use, wrapping if their coordinates leave
0..1. Slots are packed at the source images' resolution when that fits in
Q2's 640x480 PCX limit and scaled down uniformly when it does not; the
true-colour TGA written next to each PCX then keeps the full resolution in
the same layout, for engines that load replacement textures.
"""

import math
import os

import numpy as np
from PIL import Image

from . import images, shaders

PARTS = ('lower', 'upper', 'head')
PAD = 2
MAX_W, MAX_H = 640, 480


def find_variants(vfs, model_dir):
    names = []
    for path in vfs.list(model_dir + 'lower_', '.skin'):
        v = os.path.basename(path)[len('lower_'):-len('.skin')]
        if all(vfs.exists('%s%s_%s.skin' % (model_dir, p, v)) for p in ('upper', 'head')):
            names.append(v)
    names.sort(key=lambda v: (v != 'default', v))
    return names


def parse_skin(text):
    """Q3 RE_RegisterSkin: 'surface,shader' pairs; tag_ lines are ignored."""
    out = {}
    for line in text.replace('\r', '\n').split('\n'):
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        surf, _, shader = line.partition(',')
        surf = surf.strip().lower()
        if not surf or 'tag_' in surf:
            continue
        out[surf] = shader.strip()
    return out


def _lookup(skin, surface):
    """Shader for a surface: exact name, else a unique entry that extends it
    with a suffix (or that it extends), as in skins written for an edited mesh."""
    if surface in skin:
        return skin[surface]
    near = [k for k in skin if k.startswith(surface + '_') or surface.startswith(k + '_')]
    return skin[near[0]] if len(near) == 1 else None


class SkinSet:
    """Texture assignment of every (part, surface) in every variant."""

    def __init__(self, vfs, model_dir, parts, variants):
        self.vfs = vfs
        self.variants = variants
        self.shaders = shaders.load_all(vfs)
        self.refs = {}          # (part, surface index) -> [TextureRef per variant]
        self.warnings = []
        for part in PARTS:
            model = parts[part].model
            skins = [parse_skin(vfs.read('%s%s_%s.skin' % (model_dir, part, v)).decode('latin1'))
                     for v in variants]
            for si, surf in enumerate(model.surfaces):
                refs = []
                for v, skin in zip(variants, skins):
                    name = _lookup(skin, surf.name)
                    if name is None:
                        name = surf.shaders[0] if surf.shaders else ''
                    ref = shaders.resolve(name, vfs, self.shaders, model_dir)
                    if ref.missing and refs:
                        # fall back to the first variant's texture, not a checkerboard
                        self.warnings.append('%s %s/%s: texture %s not found, using %s'
                                             % (v, part, surf.name, ref.missing, variants[0]))
                        ref = refs[0]
                    elif ref.missing:
                        self.warnings.append('%s %s/%s: texture %s not found'
                                             % (v, part, surf.name, ref.missing))
                    elif ref.relocated:
                        self.warnings.append('%s %s/%s: %s not found, used %s'
                                             % (v, part, surf.name, ref.relocated, ref.image))
                    refs.append(ref)
                self.refs[(part, si)] = refs

    def visible(self, part, si):
        return not self.refs[(part, si)][0].nodraw

    def two_sided(self, part, si):
        return self.refs[(part, si)][0].two_sided


class Slot:
    def __init__(self, refs):
        self.refs = refs                # TextureRef per variant
        self.members = []               # (part, surface index)
        self.u0 = self.v0 = self.u1 = self.v1 = 0.0
        self.w = self.h = 1             # region size in texels at full resolution
        self.x = self.y = 0             # placement in the atlas (PCX scale), excluding padding
        self.pw = self.ph = 1           # region size at PCX scale


def _image_size(vfs, ref, cache):
    if ref.image is None:
        return (64, 64)
    if ref.image not in cache:
        cache[ref.image] = images.load_image(vfs.read(ref.image))
    img = cache[ref.image]
    return img.shape[1], img.shape[0]


def _shelf_pack(sizes, width):
    """Place (w, h) boxes in rows of the given width; return positions and height."""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    pos = [None] * len(sizes)
    x = y = row_h = 0
    for i in order:
        w, h = sizes[i]
        if w > width:
            return None, None
        if x + w > width:
            y += row_h
            x = row_h = 0
        pos[i] = (x, y)
        x += w
        row_h = max(row_h, h)
    return pos, y + row_h


class Atlas:
    def __init__(self, skinset, parts):
        self.skinset = skinset
        self.cache = {}
        slots = {}
        for part in PARTS:
            for si, surf in enumerate(parts[part].model.surfaces):
                if not skinset.visible(part, si):
                    continue
                refs = skinset.refs[(part, si)]
                key = tuple(r.key() for r in refs)
                slot = slots.get(key)
                if slot is None:
                    slot = slots[key] = Slot(refs)
                slot.members.append((part, si))
        self.slots = list(slots.values())
        for slot in self.slots:
            self._measure(slot, parts)
        self._pack()

    def _measure(self, slot, parts):
        st = np.concatenate([parts[p].model.surfaces[si].st for p, si in slot.members])
        tw = max(_image_size(self.skinset.vfs, r, self.cache)[0] for r in slot.refs)
        th = max(_image_size(self.skinset.vfs, r, self.cache)[1] for r in slot.refs)
        umin, vmin = st.min(axis=0)
        umax, vmax = st.max(axis=0)
        # snap to whole texels of the largest variant image
        slot.u0 = math.floor(umin * tw + 1e-4) / tw
        slot.u1 = max(math.ceil(umax * tw - 1e-4) / tw, slot.u0 + 1.0 / tw)
        slot.v0 = math.floor(vmin * th + 1e-4) / th
        slot.v1 = max(math.ceil(vmax * th - 1e-4) / th, slot.v0 + 1.0 / th)
        slot.w = max(1, int(round((slot.u1 - slot.u0) * tw)))
        slot.h = max(1, int(round((slot.v1 - slot.v0) * th)))

    def _pack(self):
        scale = 1.0
        while True:
            sizes = [(max(1, int(round(s.w * scale))) + 2 * PAD,
                      max(1, int(round(s.h * scale))) + 2 * PAD) for s in self.slots]
            best = None
            widest = max(w for w, _ in sizes)
            for width in range(widest + (widest & 1), MAX_W + 1, 2):
                pos, height = _shelf_pack(sizes, width)
                if pos is None or height > MAX_H:
                    continue
                height += height & 1
                cost = (max(width, height), width * height)
                if best is None or cost < best[0]:
                    best = (cost, width, height, pos)
            if best is not None:
                break
            scale *= 0.9
        _, self.width, self.height, pos = best
        self.scale = scale
        for slot, (x, y), (w, h) in zip(self.slots, pos, sizes):
            slot.x, slot.y = x + PAD, y + PAD
            slot.pw, slot.ph = w - 2 * PAD, h - 2 * PAD
        # the true-colour copy keeps full resolution when the PCX had to shrink
        self.hires = 1 if scale >= 0.999 else min(4, math.ceil(1.0 / scale))

    def remap(self, part, si, st):
        """Surface texture coordinates -> atlas coordinates in 0..1."""
        for slot in self.slots:
            if (part, si) in slot.members:
                u = (slot.x + (st[:, 0] - slot.u0) / (slot.u1 - slot.u0) * slot.pw) / self.width
                v = (slot.y + (st[:, 1] - slot.v0) / (slot.v1 - slot.v0) * slot.ph) / self.height
                return np.stack([u, v], axis=1)
        raise KeyError((part, si))

    # --------------------------------------------------------------- images

    def _texture(self, ref):
        if ref.nodraw:
            # hidden in this variant but part of the shared mesh: cut it out
            return np.zeros((8, 8, 4), np.uint8)
        if ref.image is None:
            img = np.full((64, 64, 4), 128, np.uint8)
            img[::8, :, :3] = img[:, ::8, :3] = 200
            return img
        img = self.cache.get(ref.image)
        if img is None:
            img = self.cache[ref.image] = images.load_image(self.skinset.vfs.read(ref.image))
        if ref.underlay:
            img = self._flatten(img, ref.underlay)
        elif ref.alpha_test:
            img = images.bleed(img)
        else:
            img = img.copy()
            img[..., 3] = 255
        return img

    def _flatten(self, img, underlay):
        """Composite an alpha-blended stage over the stage below it. An
        environment map below depends on the view, so its average colour
        stands in for it."""
        path, (ss, ts), env = underlay
        under = self.cache.get(path)
        if under is None:
            under = self.cache[path] = images.load_image(self.skinset.vfs.read(path))
        h, w = img.shape[:2]
        if env:
            base = np.broadcast_to(under.reshape(-1, 4).mean(axis=0).astype(np.float32), (h, w, 4))
        else:
            uh, uw = under.shape[:2]
            ys = (np.arange(h) * ts * uh / h).astype(int) % uh
            xs = (np.arange(w) * ss * uw / w).astype(int) % uw
            base = under[ys][:, xs].astype(np.float32)
        a = img[..., 3:4].astype(np.float32) / 255
        out = img.astype(np.float32) * a + base * (1 - a)
        out[..., 3] = 255
        return out.astype(np.uint8)

    def _region(self, ref, slot, w, h):
        tex = self._texture(ref)
        th, tw = tex.shape[:2]
        fx, fy = math.floor(slot.u0), math.floor(slot.v0)
        kx = max(1, math.ceil(slot.u1) - fx)
        ky = max(1, math.ceil(slot.v1) - fy)
        tiled = np.tile(tex, (ky, kx, 1)) if (kx, ky) != (1, 1) else tex
        box = ((slot.u0 - fx) * tw, (slot.v0 - fy) * th, (slot.u1 - fx) * tw, (slot.v1 - fy) * th)
        im = Image.fromarray(tiled, 'RGBA').resize((w, h), Image.LANCZOS, box=box)
        return np.asarray(im)

    def render(self, variant_index, factor=1):
        """RGBA atlas for one variant at `factor` times the PCX resolution."""
        W, H, pad = self.width * factor, self.height * factor, PAD * factor
        out = np.zeros((H, W, 4), np.uint8)
        for slot in self.slots:
            w, h = slot.pw * factor, slot.ph * factor
            ref = slot.refs[variant_index]
            if ref.nodraw and not slot.refs[0].nodraw:
                # hidden in this variant only: first variant's colours, fully transparent,
                # so renderers without alpha test still show something sensible
                region = self._region(slot.refs[0], slot, w, h).copy()
                region[..., 3] = 0
            else:
                region = self._region(ref, slot, w, h)
            region = np.pad(region, ((pad, pad), (pad, pad), (0, 0)), mode='edge')
            x, y = slot.x * factor - pad, slot.y * factor - pad
            out[y:y + h + 2 * pad, x:x + w + 2 * pad] = region
        return out

    def uses_alpha(self, variant_index):
        return any(s.refs[variant_index].alpha_test or s.refs[variant_index].nodraw
                   for s in self.slots)

    def head_region(self, rgba, factor=1):
        """Crop of the head's texture, a stand-in when a variant has no icon."""
        for slot in self.slots:
            if any(p == 'head' for p, _ in slot.members):
                x, y = slot.x * factor, slot.y * factor
                return rgba[y:y + slot.ph * factor, x:x + slot.pw * factor]
        return rgba
