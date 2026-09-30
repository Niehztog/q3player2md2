"""Quake II MD2 writer, reader and validator.

The GL command builder is a port of BuildGlCmds/StripLength/FanLength from
id's qdata (models.c), using an edge table instead of qdata's linear scan.
"""

import struct

import numpy as np

from .anorms import ANORMS

MD2_IDENT = b'IDP2'
MD2_VERSION = 8

# The smallest limits among the engines this targets: id's Quake II and
# yquake2 (MAX_VERTS, MAX_TRIANGLES, MAX_FRAMES, MAX_LBM_HEIGHT) and q2pro.
MAX_VERTS = 2048
MAX_TRIANGLES = 4096
MAX_FRAMES = 512
MAX_SKINS = 32
MAX_SKINNAME = 64
MAX_SKINHEIGHT = 480


class Frame:
    def __init__(self, name, xyz, normal_idx):
        self.name = name            # up to 15 characters
        self.xyz = xyz              # (V, 3) float
        self.normal_idx = normal_idx  # (V,) uint8 index into ANORMS


class Model:
    """In-memory MD2: shared topology, per-frame positions."""

    def __init__(self, skinwidth, skinheight, skins, st, tris_xyz, tris_st, frames):
        self.skinwidth = skinwidth
        self.skinheight = skinheight
        self.skins = skins          # list of skin paths
        self.st = st                # (S, 2) int, texel coordinates
        self.tris_xyz = tris_xyz    # (T, 3) int
        self.tris_st = tris_st      # (T, 3) int
        self.frames = frames        # list of Frame
        self.glcmds = None          # list of (is_strip, [(s, t, xyz_index), ...]) after reading

    @property
    def num_xyz(self):
        return len(self.frames[0].xyz)


def nearest_normal(normals):
    """Unit vectors (N, 3) -> index of the closest of the 162 MD2 normals."""
    return np.argmax(normals @ ANORMS.T, axis=1).astype(np.uint8)


# ---------------------------------------------------------------- GL commands

def build_glcmds(tris_xyz, tris_st):
    """Return the MD2 GL command list as a list of (is_strip, [(xyz, st), ...])."""
    tris = [(tuple(int(v) for v in x), tuple(int(v) for v in s))
            for x, s in zip(tris_xyz, tris_st)]
    edges = {}
    for i, (x, s) in enumerate(tris):
        for k in range(3):
            key = (x[k], s[k], x[(k + 1) % 3], s[(k + 1) % 3])
            edges.setdefault(key, []).append((i, k))
    used = [False] * len(tris)

    def match(m1, st1, m2, st2, taken):
        for j, k in edges.get((m1, st1, m2, st2), ()):
            if not used[j] and j not in taken:
                return j, k
        return None

    def strip_length(start, startv):
        x, s = tris[start]
        verts = [(x[(startv + n) % 3], s[(startv + n) % 3]) for n in range(3)]
        taken = [start]
        m1, st1 = x[(startv + 2) % 3], s[(startv + 2) % 3]
        m2, st2 = x[(startv + 1) % 3], s[(startv + 1) % 3]
        while True:
            hit = match(m1, st1, m2, st2, taken)
            if hit is None:
                break
            j, k = hit
            cx, cs = tris[j]
            new = (cx[(k + 2) % 3], cs[(k + 2) % 3])
            if len(taken) & 1:
                m2, st2 = new
            else:
                m1, st1 = new
            verts.append(new)
            taken.append(j)
        return verts, taken

    def fan_length(start, startv):
        x, s = tris[start]
        verts = [(x[(startv + n) % 3], s[(startv + n) % 3]) for n in range(3)]
        taken = [start]
        m1, st1 = x[startv % 3], s[startv % 3]
        m2, st2 = x[(startv + 2) % 3], s[(startv + 2) % 3]
        while True:
            hit = match(m1, st1, m2, st2, taken)
            if hit is None:
                break
            j, k = hit
            cx, cs = tris[j]
            m2, st2 = cx[(k + 2) % 3], cs[(k + 2) % 3]
            verts.append((m2, st2))
            taken.append(j)
        return verts, taken

    commands = []
    for i in range(len(tris)):
        if used[i]:
            continue
        best = None
        for is_strip in (False, True):
            for startv in range(3):
                verts, taken = (strip_length if is_strip else fan_length)(i, startv)
                if best is None or len(taken) > len(best[2]):
                    best = (is_strip, verts, taken)
        is_strip, verts, taken = best
        for j in taken:
            used[j] = True
        commands.append((is_strip, verts))
    return commands


def glcmd_triangles(commands):
    """Expand GL commands back into triangles the way OpenGL draws them."""
    out = []
    for is_strip, verts in commands:
        for n in range(len(verts) - 2):
            if is_strip:
                a, b, c = verts[n], verts[n + 1], verts[n + 2]
                if n & 1:
                    a, b = b, a
            else:
                a, b, c = verts[0], verts[n + 1], verts[n + 2]
            out.append((a, b, c))
    return out


# ---------------------------------------------------------------------- write

def write(model, path):
    frames = model.frames
    num_frames = len(frames)
    num_xyz = model.num_xyz
    num_tris = len(model.tris_xyz)
    problems = limits_problems(model)
    if problems:
        raise ValueError('; '.join(problems))

    commands = build_glcmds(model.tris_xyz, model.tris_st)
    w, h = float(model.skinwidth), float(model.skinheight)
    glcmds = bytearray()
    for is_strip, verts in commands:
        glcmds += struct.pack('<i', len(verts) if is_strip else -len(verts))
        for xyz_index, st_index in verts:
            s, t = model.st[st_index]
            glcmds += struct.pack('<ffi', s / w, t / h, xyz_index)
    glcmds += struct.pack('<i', 0)

    framesize = 40 + 4 * num_xyz
    ofs_skins = 68
    ofs_st = ofs_skins + MAX_SKINNAME * len(model.skins)
    ofs_tris = ofs_st + 4 * len(model.st)
    ofs_frames = ofs_tris + 12 * num_tris
    ofs_glcmds = ofs_frames + framesize * num_frames
    ofs_end = ofs_glcmds + len(glcmds)

    out = bytearray()
    out += struct.pack('<4s16i', MD2_IDENT, MD2_VERSION, model.skinwidth, model.skinheight,
                       framesize, len(model.skins), num_xyz, len(model.st), num_tris,
                       len(glcmds) // 4, num_frames, ofs_skins, ofs_st, ofs_tris,
                       ofs_frames, ofs_glcmds, ofs_end)
    for skin in model.skins:
        out += skin.encode('latin1').ljust(MAX_SKINNAME, b'\0')
    out += np.asarray(model.st, '<i2').tobytes()
    tris = np.concatenate([np.asarray(model.tris_xyz, '<i2'), np.asarray(model.tris_st, '<i2')], axis=1)
    out += tris.tobytes()
    for fr in frames:
        xyz = np.asarray(fr.xyz, np.float64)
        lo = xyz.min(axis=0)
        hi = xyz.max(axis=0)
        scale = np.maximum((hi - lo) / 255.0, 1e-6)
        q = np.clip(np.rint((xyz - lo) / scale), 0, 255).astype(np.uint8)
        out += struct.pack('<6f', *scale, *lo)
        out += fr.name.encode('latin1')[:15].ljust(16, b'\0')
        out += np.concatenate([q, fr.normal_idx.reshape(-1, 1)], axis=1).astype(np.uint8).tobytes()
    out += glcmds
    assert len(out) == ofs_end
    with open(path, 'wb') as f:
        f.write(out)
    return len(commands)


def limits_problems(model):
    p = []
    if model.num_xyz > MAX_VERTS:
        p.append('%d vertices (limit %d)' % (model.num_xyz, MAX_VERTS))
    if len(model.tris_xyz) > MAX_TRIANGLES:
        p.append('%d triangles (limit %d)' % (len(model.tris_xyz), MAX_TRIANGLES))
    if len(model.frames) > MAX_FRAMES:
        p.append('%d frames (limit %d)' % (len(model.frames), MAX_FRAMES))
    if len(model.skins) > MAX_SKINS:
        p.append('%d skins (limit %d)' % (len(model.skins), MAX_SKINS))
    for s in model.skins:
        if len(s) >= MAX_SKINNAME:
            p.append('skin name too long: %s' % s)
    if model.skinheight > MAX_SKINHEIGHT:
        p.append('skin height %d (limit %d)' % (model.skinheight, MAX_SKINHEIGHT))
    return p


# ----------------------------------------------------------------------- read

def read(data):
    h = struct.unpack_from('<4s16i', data, 0)
    (ident, version, skinwidth, skinheight, framesize, num_skins, num_xyz, num_st,
     num_tris, num_glcmds, num_frames, ofs_skins, ofs_st, ofs_tris, ofs_frames,
     ofs_glcmds, ofs_end) = h
    if ident != MD2_IDENT or version != MD2_VERSION:
        raise ValueError('not an MD2')
    if ofs_end > len(data):
        raise ValueError('truncated MD2')
    skins = [data[ofs_skins + i * 64:ofs_skins + i * 64 + 64].split(b'\0')[0].decode('latin1')
             for i in range(num_skins)]
    st = np.frombuffer(data, '<i2', num_st * 2, ofs_st).reshape(-1, 2).astype(np.int32)
    tris = np.frombuffer(data, '<i2', num_tris * 6, ofs_tris).reshape(-1, 6).astype(np.int32)
    frames = []
    for i in range(num_frames):
        o = ofs_frames + i * framesize
        scale = np.array(struct.unpack_from('<3f', data, o))
        translate = np.array(struct.unpack_from('<3f', data, o + 12))
        name = data[o + 24:o + 40].split(b'\0')[0].decode('latin1')
        v = np.frombuffer(data, np.uint8, num_xyz * 4, o + 40).reshape(-1, 4)
        frames.append(Frame(name, v[:, :3] * scale + translate, v[:, 3].copy()))
    m = Model(skinwidth, skinheight, skins, st, tris[:, :3], tris[:, 3:], frames)
    cmds = []
    o = ofs_glcmds
    end = ofs_glcmds + num_glcmds * 4
    while o < end:
        (count,) = struct.unpack_from('<i', data, o)
        o += 4
        if count == 0:
            break
        verts = []
        for _ in range(abs(count)):
            s, t, idx = struct.unpack_from('<ffi', data, o)
            o += 12
            verts.append((s, t, idx))
        cmds.append((count > 0, verts))
    m.glcmds = cmds
    return m


def validate(data):
    """Structural checks a Quake II engine would trip over. Returns a list of problems."""
    m = read(data)
    problems = limits_problems(m)
    nx = m.num_xyz
    if m.tris_xyz.size and (m.tris_xyz.min() < 0 or m.tris_xyz.max() >= nx):
        problems.append('triangle xyz index out of range')
    if m.tris_st.size and (m.tris_st.min() < 0 or m.tris_st.max() >= len(m.st)):
        problems.append('triangle st index out of range')
    # Every triangle must come out of the GL commands exactly once, same winding.
    def canon(tri):
        i = tri.index(min(tri))
        return tri[i:] + tri[:i]
    want = sorted(canon(tuple(int(v) for v in t)) for t in m.tris_xyz)
    got = []
    for is_strip, verts in m.glcmds:
        if any(idx < 0 or idx >= nx for _, _, idx in verts):
            problems.append('GL command vertex index out of range')
            break
    cmds = [(is_strip, [idx for _, _, idx in verts]) for is_strip, verts in m.glcmds]
    for a, b, c in glcmd_triangles(cmds):
        got.append(canon((a, b, c)))
    if sorted(got) != want:
        problems.append('GL commands do not reproduce the triangle list (%d vs %d)'
                        % (len(got), len(want)))
    return problems
