"""Palette, quantization and image file helpers."""

import io
import struct

import numpy as np
from PIL import Image

TRANSPARENT = 255       # Q2 treats palette index 255 as see-through


def load_palette(vfs):
    """The Quake II palette, from pics/colormap.pcx: (256, 3) uint8."""
    data = vfs.read('pics/colormap.pcx')
    if len(data) < 769 or data[-769] != 0x0c:
        raise ValueError('pics/colormap.pcx has no palette')
    return np.frombuffer(data[-768:], np.uint8).reshape(256, 3).copy()


def load_image(data):
    """Decode TGA/JPEG/PNG/PCX bytes -> (H, W, 4) uint8 RGBA."""
    im = Image.open(io.BytesIO(data))
    return np.asarray(im.convert('RGBA')).copy()


class Quantizer:
    """Nearest palette colour through a 64x64x64 lookup table.

    Index 255 is left out: it is transparent in Q2. Distances are weighted
    towards green, a cheap stand-in for perceived brightness."""

    def __init__(self, palette):
        self.palette = palette
        pal = palette[:255].astype(np.float32)
        levels = (np.arange(64, dtype=np.float32) * 4 + 2)
        grid = np.stack(np.meshgrid(levels, levels, levels, indexing='ij'), -1).reshape(-1, 3)
        weights = np.array([2.0, 4.0, 3.0], np.float32)
        lut = np.empty(len(grid), np.uint8)
        for start in range(0, len(grid), 8192):
            chunk = grid[start:start + 8192]
            d = (((chunk[:, None, :] - pal[None, :, :]) ** 2) * weights).sum(-1)
            lut[start:start + 8192] = np.argmin(d, axis=1)
        self.lut = lut.reshape(64, 64, 64)

    def __call__(self, rgba, alpha_cutout=False):
        idx = self.lut[rgba[..., 0] >> 2, rgba[..., 1] >> 2, rgba[..., 2] >> 2]
        if alpha_cutout:
            idx = np.where(rgba[..., 3] < 128, TRANSPARENT, idx)
        return idx.astype(np.uint8)


def write_pcx(path, indices, palette):
    """8-bit RLE PCX in the form id's LoadPCX reads: runs never cross a row,
    bytes_per_line equals the width, palette appended after 0x0c."""
    h, w = indices.shape
    if w % 2:
        raise ValueError('PCX width must be even for Quake II')
    if w > 640 or h > 480:
        raise ValueError('Quake II cannot load PCX files larger than 640x480')
    header = struct.pack('<4B6H48s2B4H54s', 0x0a, 5, 1, 8, 0, 0, w - 1, h - 1, 72, 72,
                         b'\0' * 48, 0, 1, w, 1, 0, 0, b'\0' * 54)
    body = bytearray()
    for row in indices:
        x = 0
        row = row.tolist()
        while x < w:
            v = row[x]
            run = 1
            while x + run < w and run < 63 and row[x + run] == v:
                run += 1
            if run > 1 or (v & 0xc0) == 0xc0:
                body.append(0xc0 | run)
            body.append(v)
            x += run
    with open(path, 'wb') as f:
        f.write(header)
        f.write(body)
        f.write(b'\x0c')
        f.write(palette.astype(np.uint8).tobytes())


def write_tga(path, rgba, keep_alpha):
    im = Image.fromarray(rgba if keep_alpha else rgba[..., :3], 'RGBA' if keep_alpha else 'RGB')
    im.save(path, format='TGA', rle=False)


def palette_to_rgba(indices, palette):
    rgba = np.empty(indices.shape + (4,), np.uint8)
    rgba[..., :3] = palette[indices]
    rgba[..., 3] = np.where(indices == TRANSPARENT, 0, 255)
    return rgba


def bleed(rgba, passes=24):
    """Give fully transparent texels the colour of their nearest opaque
    neighbours. Engines that do not alpha-test model skins (q2pro) then show
    that colour instead of whatever the source had there, and filtering at
    cut-out edges does not pull in black. Alpha is left as it was."""
    out = rgba.copy()
    have = rgba[..., 3] >= 128
    if have.all() or not have.any():
        return out
    rgb = out[..., :3].astype(np.float32)
    for _ in range(passes):
        missing = ~have
        if not missing.any():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(have.shape, np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            src = np.roll(np.roll(have, dy, 0), dx, 1)
            acc += np.roll(np.roll(rgb, dy, 0), dx, 1) * src[..., None]
            cnt += src
        grow = missing & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        have = have | grow
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out
