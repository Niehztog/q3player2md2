"""Visible weapon models (weapon.md2, w_*.md2) that follow the hand.

A Q2 player's weapon model uses the same frame numbers as tris.md2. Here each
one is a Q2 world weapon model held at the torso's tag_weapon in every frame,
with the scale and offset gildor2/Quake2 uses to attach the same models to
Q3 players (resource/res/baseq2/models/weapons/*.md2.cfg there). The source
models come from the Q2 data; weapons whose model is missing are skipped, and
the client then falls back to weapon.md2.
"""

import numpy as np

from . import md2
from .anorms import ANORMS

# name: (world model, scale, offset in tag space before scaling)
WEAPONS = {
    'weapon.md2':         ('models/weapons/g_shotg/tris.md2', 0.5, (0, -1, -18)),
    'w_blaster.md2':      ('models/weapons/g_blast/tris.md2', 0.5, (3, -1, -18)),
    'w_shotgun.md2':      ('models/weapons/g_shotg/tris.md2', 0.5, (0, -1, -18)),
    'w_sshotgun.md2':     ('models/weapons/g_shotg2/tris.md2', 0.5, (0, -1, -20)),
    'w_machinegun.md2':   ('models/weapons/g_machn/tris.md2', 0.5, (-4, -1, -18)),
    'w_chaingun.md2':     ('models/weapons/g_chain/tris.md2', 0.5, (9, -1, -18)),
    'a_grenades.md2':     ('models/items/ammo/grenades/medium/tris.md2', 0.3, (-3, 0, 0)),
    'w_glauncher.md2':    ('models/weapons/g_launch/tris.md2', 0.5, (7, -1, -16)),
    'w_rlauncher.md2':    ('models/weapons/g_rocket/tris.md2', 0.5, (9, -1, -15)),
    'w_hyperblaster.md2': ('models/weapons/g_hyperb/tris.md2', 0.5, (7, -1, -17)),
    'w_railgun.md2':      ('models/weapons/g_rail/tris.md2', 0.5, (0, -1, -16)),
    'w_bfg.md2':          ('models/weapons/g_bfg/tris.md2', 0.5, (-4, -2, -32)),
    # The Reckoning
    'w_phalanx.md2':      ('models/weapons/g_shotx/tris.md2', 0.5, (8, 0, -14)),
    'w_ripper.md2':       ('models/weapons/g_boom/tris.md2', 0.5, (10, 0, -18)),
    # Ground Zero
    'w_chainfist.md2':    ('models/weapons/g_chainf/tris.md2', 1.0, (6, 0, -19)),
    'w_disrupt.md2':      ('models/weapons/g_dist/tris.md2', 0.5, (6, 0, -15)),
    'w_etfrifle.md2':     ('models/weapons/g_etf_rifle/tris.md2', 0.7, (8, 0, -16)),
    'w_plasma.md2':       ('models/weapons/g_beamer/tris.md2', 0.5, (2, 0, -22)),
    'w_plauncher.md2':    ('models/weapons/g_plaunch/tris.md2', 0.5, (7, 0, -16)),
    # Threewave CTF: the grapple has no world model, and id's own male
    # w_grapple.md2 holds the unused flare gun instead. Placed where id put
    # it relative to the other weapons (fitted against their male w_*.md2)
    'w_grapple.md2':      ('models/weapons/g_flareg/tris.md2', 0.45, (0, 0, -17)),
}


def build(source, scale, offset, baked_frames):
    """Q2 world model (md2.Model) held at tag_weapon -> md2.Model with the player's frames."""
    base = source.frames[0]
    verts = (np.asarray(base.xyz, np.float32) + np.asarray(offset, np.float32)) * scale
    normals = ANORMS[base.normal_idx]
    frames = []
    for bf in baked_frames:
        origin, axis = bf.weapon
        xyz = origin + verts @ axis
        frames.append(md2.Frame(bf.name, xyz, md2.nearest_normal(normals @ axis)))
    return md2.Model(source.skinwidth, source.skinheight, source.skins[:1],
                     source.st, source.tris_xyz, source.tris_st, frames)


def placeholder(baked_frames):
    """A one-triangle weapon.md2 hidden inside the hand, for when no Q2 data is
    available: clients reject a player model without weapon.md2."""
    frames = []
    for bf in baked_frames:
        origin, _ = bf.weapon
        xyz = np.array([origin, origin + [0.01, 0, 0], origin + [0, 0.01, 0]], np.float32)
        frames.append(md2.Frame(bf.name, xyz, np.zeros(3, np.uint8)))
    return md2.Model(8, 8, [], np.zeros((3, 2), np.int32), np.array([[0, 1, 2]]),
                     np.array([[0, 1, 2]]), frames)
