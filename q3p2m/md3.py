"""Quake III MD3 reader."""

import struct

import numpy as np

MD3_IDENT = b'IDP3'
MD3_VERSION = 15
MD3_XYZ_SCALE = 1.0 / 64


class Surface:
    def __init__(self, name, shaders, tris, st, xyz, normals):
        self.name = name            # lowercase, as the Q3 renderer compares it
        self.shaders = shaders      # shader names embedded in the file
        self.tris = tris            # (T, 3) int32 vertex indices
        self.st = st                # (V, 2) float32
        self.xyz_raw = xyz          # (F, V, 3) int16, units of 1/64
        self.xyz = xyz.astype(np.float32) * MD3_XYZ_SCALE
        self.normals = normals      # (F, V, 3) float32, unit length


class Model:
    def __init__(self, name, frame_names, tags, surfaces):
        self.name = name
        self.frame_names = frame_names
        self.num_frames = len(frame_names)
        self.tags = tags            # name -> (origins (F, 3), axes (F, 3, 3), rows = axis vectors)
        self.surfaces = surfaces


def _cstr(b):
    return b.split(b'\0')[0].decode('latin1')


def decode_normals(packed):
    """MD3 lat/long normals -> unit vectors, exactly as tr_surface.c decodes them."""
    lat = ((packed >> 8) & 0xff).astype(np.float32) * (2 * np.pi / 256)
    lng = (packed & 0xff).astype(np.float32) * (2 * np.pi / 256)
    return np.stack([np.cos(lat) * np.sin(lng),
                     np.sin(lat) * np.sin(lng),
                     np.cos(lng)], axis=-1).astype(np.float32)


def load(data, name='?'):
    ident, version = struct.unpack_from('<4si', data, 0)
    if ident != MD3_IDENT or version != MD3_VERSION:
        raise ValueError('%s: not an MD3 (ident %r, version %d)' % (name, ident, version))
    (flags, num_frames, num_tags, num_surfaces, num_skins,
     ofs_frames, ofs_tags, ofs_surfaces, ofs_end) = struct.unpack_from('<9i', data, 72)
    if num_frames < 1:
        raise ValueError('%s: no frames' % name)

    frame_names = []
    for i in range(num_frames):
        frame_names.append(_cstr(data[ofs_frames + i * 56 + 40:ofs_frames + i * 56 + 56]))

    tags = {}
    tag_origins = {}
    tag_axes = {}
    for f in range(num_frames):
        for t in range(num_tags):
            o = ofs_tags + (f * num_tags + t) * 112
            tname = _cstr(data[o:o + 64])
            vals = struct.unpack_from('<12f', data, o + 64)
            tag_origins.setdefault(tname, []).append(vals[0:3])
            tag_axes.setdefault(tname, []).append((vals[3:6], vals[6:9], vals[9:12]))
    for tname in tag_origins:
        tags[tname] = (np.array(tag_origins[tname], np.float32),
                       np.array(tag_axes[tname], np.float32))

    surfaces = []
    o = ofs_surfaces
    for _ in range(num_surfaces):
        (sident,) = struct.unpack_from('<4s', data, o)
        if sident != MD3_IDENT:
            raise ValueError('%s: bad surface ident at %d' % (name, o))
        sname = _cstr(data[o + 4:o + 68]).lower()
        (sflags, s_frames, s_shaders, s_verts, s_tris, ofs_tris, ofs_shaders,
         ofs_st, ofs_xyz, s_end) = struct.unpack_from('<10i', data, o + 68)
        if s_frames != num_frames:
            raise ValueError('%s: surface %s has %d frames, model has %d'
                             % (name, sname, s_frames, num_frames))
        shaders = [_cstr(data[o + ofs_shaders + i * 68:o + ofs_shaders + i * 68 + 64])
                   for i in range(s_shaders)]
        tris = np.frombuffer(data, '<i4', s_tris * 3, o + ofs_tris).reshape(-1, 3).astype(np.int32)
        st = np.frombuffer(data, '<f4', s_verts * 2, o + ofs_st).reshape(-1, 2).astype(np.float32)
        raw = np.frombuffer(data, '<i2', num_frames * s_verts * 4, o + ofs_xyz).reshape(num_frames, s_verts, 4)
        xyz = raw[:, :, 0:3].copy()
        normals = decode_normals(raw[:, :, 3].astype(np.int32) & 0xffff)
        if tris.size and (tris.min() < 0 or tris.max() >= s_verts):
            raise ValueError('%s: surface %s has out-of-range triangle indices' % (name, sname))
        surfaces.append(Surface(sname, shaders, tris, st, xyz, normals))
        o += s_end

    return Model(name, frame_names, tags, surfaces)
