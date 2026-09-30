"""Assemble the three Quake III parts per Quake II frame.

The tag math is Q3's CG_PositionRotatedEntityOnTag with R_LerpTag: tags are
interpolated linearly and their axes renormalized; each part's axis is its own
rotation times the tag axis times the parent's axis (rows are axis vectors).
Legs sit at the origin facing +X, like Q2 player models. Torso and head get no
extra rotation except the pain twitch.
"""

import math

import numpy as np

from . import mapping

FEET_Z = -24.0      # pmove mins[2] in both games


class PartPose:
    def __init__(self, verts, normals, tags):
        self.verts = verts          # (V, 3)
        self.normals = normals      # (V, 3)
        self.tags = tags            # name -> (origin (3,), axis (3, 3))


class Part:
    """One MD3 with all its surfaces flattened into one vertex array."""

    def __init__(self, model):
        self.model = model
        self.xyz = np.concatenate([s.xyz for s in model.surfaces], axis=1)          # (F, V, 3)
        self.xyz_raw = np.concatenate([s.xyz_raw for s in model.surfaces], axis=1)  # (F, V, 3)
        self.normals = np.concatenate([s.normals for s in model.surfaces], axis=1)
        self.offsets = np.cumsum([0] + [s.xyz.shape[1] for s in model.surfaces])
        self.warned = set()

    def frame(self, f):
        if f >= self.model.num_frames:
            if f not in self.warned:
                self.warned.add(f)
                print('warning: %s has %d frames, animation.cfg wants frame %d; using the last'
                      % (self.model.name, self.model.num_frames, f))
            f = self.model.num_frames - 1
        return max(f, 0)

    def pose(self, fa, fb, t):
        fa, fb = self.frame(fa), self.frame(fb)
        verts = self.xyz[fa] * (1 - t) + self.xyz[fb] * t
        normals = self.normals[fa] * (1 - t) + self.normals[fb] * t
        tags = {}
        for name, (origins, axes) in self.model.tags.items():
            o = origins[fa] * (1 - t) + origins[fb] * t
            a = axes[fa] * (1 - t) + axes[fb] * t
            tags[name] = (o, _normalize_rows(a))
        return PartPose(verts, normals, tags)


def _normalize_rows(a):
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.where(n == 0, 1, n)


def blend(p, q, w):
    """w = 0 gives p, w = 1 gives q."""
    tags = {}
    for name in p.tags:
        if name in q.tags:
            o = p.tags[name][0] * (1 - w) + q.tags[name][0] * w
            a = p.tags[name][1] * (1 - w) + q.tags[name][1] * w
            tags[name] = (o, _normalize_rows(a))
    return PartPose(p.verts * (1 - w) + q.verts * w, p.normals * (1 - w) + q.normals * w, tags)


def angles_to_axis(pitch, yaw, roll):
    """Q3 AnglesToAxis: rows forward, left, up."""
    p, y, r = (math.radians(v) for v in (pitch, yaw, roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    forward = (cp * cy, cp * sy, -sp)
    right = (-sr * sp * cy + cr * sy, -sr * sp * sy - cr * cy, -sr * cp)
    up = (cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp)
    return np.array([forward, [-v for v in right], up], np.float32)


def _tag(pose, name, part_name):
    try:
        return pose.tags[name]
    except KeyError:
        raise ValueError('%s.md3 has no %s' % (part_name, name)) from None


def assemble(legs, torso, head, torso_rotation=None):
    """Return {part: (verts, normals)} in legs space and the weapon (origin, axis)."""
    o_t, axis_t = _tag(legs, 'tag_torso', 'lower')
    if torso_rotation is not None:
        axis_t = torso_rotation @ axis_t
    o_hr, axis_hr = _tag(torso, 'tag_head', 'upper')
    o_h = o_t + o_hr @ axis_t
    axis_h = axis_hr @ axis_t
    out = {
        'lower': (legs.verts, legs.normals),
        'upper': (o_t + torso.verts @ axis_t, torso.normals @ axis_t),
        'head': (o_h + head.verts @ axis_h, head.normals @ axis_h),
    }
    if 'tag_weapon' in torso.tags:
        o_wr, axis_wr = torso.tags['tag_weapon']
        weapon = (o_t + o_wr @ axis_t, axis_wr @ axis_t)
    else:
        weapon = (o_t, axis_t)
    return out, weapon


class BakedFrame:
    def __init__(self, name, parts, weapon):
        self.name = name
        self.parts = parts      # part -> (verts, normals), scaled
        self.weapon = weapon    # (origin, axis) of tag_weapon, origin scaled


def bake(parts, cfg, scale):
    """parts: {'lower': Part, 'upper': Part, 'head': Part} -> 198 BakedFrames."""
    head_pose = parts['head'].pose(0, 0, 0.0)
    anchor = np.array([0, 0, (1 - scale) * FEET_Z], np.float32)
    frames = []
    for name, seq, i in mapping.frame_table():
        n = seq.count
        legs = parts['lower'].pose(*seq.legs.sample(cfg, i, n))
        torso = parts['upper'].pose(*seq.torso.sample(cfg, i, n))
        if seq.blend_from and i < seq.blend_frames:
            w = (i + 1) / (seq.blend_frames + 1)
            legs = blend(parts['lower'].pose(*seq.blend_from[0].sample(cfg, 0, 1)), legs, w)
            torso = blend(parts['upper'].pose(*seq.blend_from[1].sample(cfg, 0, 1)), torso, w)
        rotation = None
        if seq.twitch:
            axis, degrees = seq.twitch
            amount = degrees * (1 - i / (n - 1)) if n > 1 else degrees
            rotation = angles_to_axis(amount if axis == 'pitch' else 0, 0,
                                      amount if axis == 'roll' else 0)
        assembled, weapon = assemble(legs, torso, head_pose, rotation)
        scaled = {k: (v * scale + anchor, nrm) for k, (v, nrm) in assembled.items()}
        weapon = (weapon[0] * scale + anchor, weapon[1])
        frames.append(BakedFrame(name, scaled, weapon))
    return frames
