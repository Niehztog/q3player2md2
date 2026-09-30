"""Which Quake III animations make up each of Quake II's 198 player frames.

Quake II has one mesh and one frame number per player; Quake III animates the
legs and the torso separately. Every Q2 sequence below therefore names a legs
track and a torso track (or one track for both, for deaths), in the spirit of
the Frames_KP table in hypov8's q3_to_kp.py. The pairings follow the table in
gildor2/Quake2 server/sv_anim.cpp, which drives Q3 models from Q2 frames at
run time, plus what the Q2 game code does with each sequence:

  - pain3 and crpain double as the weapon change animation: p_weapon.c plays
    them backwards to lower the old weapon and forwards to raise the new one.
    They map to TORSO_RAISE, which reads correctly both ways.
  - jump1-2 is the take-off and jump2 is held while airborne; jump3-6 is the
    landing (p_view.c G_SetClientFrame).
  - wave08..wave01 backwards is the standing grenade throw.
  - Q3 has no pain animations; pain1/pain2 use Q3's pain twitch instead
    (CG_AddPainTwitch: a 20 degree torso roll that decays).

Q2 advances a player one frame per 100 ms server frame.
"""

import math

Q2_FRAME_TIME = 0.1
MIN_SAMPLES_PER_CYCLE = 4


def _local_to_md3(anim, local):
    return anim.first + (anim.num - 1 - local if anim.reversed else local)


def lerp_clamped(anim, p):
    """Position p (in animation frames) of a one-shot animation -> (frame_a, frame_b, t)."""
    last = max(anim.num - 1, 0)
    p = min(max(p, 0.0), float(last))
    a = int(math.floor(p))
    b = min(a + 1, last)
    return _local_to_md3(anim, a), _local_to_md3(anim, b), p - a


def lerp_cyclic(anim, p):
    """Position p of a looping animation; only its last `loop` frames repeat."""
    loop = min(anim.loop, anim.num)
    start = anim.num - loop
    p = p % loop
    a = int(math.floor(p))
    b = (a + 1) % loop
    return _local_to_md3(anim, start + a), _local_to_md3(anim, start + b), p - a


class Track:
    def resolve(self, cfg):
        return cfg[self.anim]


class Cycle(Track):
    """Loop at about native speed, fitting a whole number of cycles into the
    sequence so that Q2's own looping of the sequence is seamless.
    A Q3 animation without loop frames plays once and holds its last frame,
    so that is what Cycle shows for one."""

    def __init__(self, anim, cycles=None):
        self.anim = anim
        self.cycles = cycles

    def sample(self, cfg, i, n):
        anim = self.resolve(cfg)
        if anim.loop <= 0 or anim.num <= 1:
            return lerp_clamped(anim, anim.num - 1)
        loop = min(anim.loop, anim.num)
        k = self.cycles
        if k is None:
            k = max(1, round(n * Q2_FRAME_TIME / (loop * anim.frame_time)))
            k = min(k, max(1, n // MIN_SAMPLES_PER_CYCLE))
        return lerp_cyclic(anim, i / n * k * loop)


class Fit(Track):
    """Play once, stretched or squeezed so the first and last Q2 frames show
    the first and last Q3 frames. `team_arena` names a Team Arena animation to
    use instead when the model's animation.cfg defines those."""

    def __init__(self, anim, team_arena=None):
        self.anim = anim
        self.team_arena = team_arena

    def resolve(self, cfg):
        if self.team_arena and cfg.has_team_arena:
            return cfg[self.team_arena]
        return cfg[self.anim]

    def sample(self, cfg, i, n):
        anim = self.resolve(cfg)
        p = i * (anim.num - 1) / (n - 1) if n > 1 else 0.0
        return lerp_clamped(anim, p)


class Play(Track):
    """Play once at native speed, then continue with `then` (as Q3 does when
    a one-shot torso animation ends)."""

    def __init__(self, anim, then):
        self.anim = anim
        self.then = then

    def sample(self, cfg, i, n):
        anim = cfg[self.anim]
        t = i * Q2_FRAME_TIME
        p = t / anim.frame_time
        if p <= anim.num - 1:
            return lerp_clamped(anim, p)
        nxt = cfg[self.then]
        t2 = t - (anim.num - 1) * anim.frame_time
        if nxt.loop > 0 and nxt.num > 1:
            return lerp_cyclic(nxt, t2 / nxt.frame_time)
        return lerp_clamped(nxt, t2 / nxt.frame_time)


class Concat(Track):
    """Split the sequence: [(frames, track), ...]."""

    def __init__(self, *parts):
        self.parts = parts

    def sample(self, cfg, i, n):
        assert n == sum(c for c, _ in self.parts)
        for count, track in self.parts:
            if i < count:
                return track.sample(cfg, i, count)
            i -= count
        raise IndexError(i)


class Sequence:
    def __init__(self, name, count, digits, legs=None, torso=None, both=None,
                 twitch=None, blend_from=None, blend_frames=0):
        self.name = name
        self.count = count
        self.digits = digits
        self.legs = legs or both
        self.torso = torso or both
        self.twitch = twitch            # (axis, degrees) torso rotation, decaying to 0
        self.blend_from = blend_from    # (legs track, torso track) pose to start from
        self.blend_frames = blend_frames

    def frame_names(self):
        return ['%s%0*d' % (self.name, self.digits, i + 1) for i in range(self.count)]


IDLE = Cycle('LEGS_IDLE')
IDLECR = Cycle('LEGS_IDLECR')
STAND = Cycle('TORSO_STAND')

SEQUENCES = [
    Sequence('stand',   40, 2, legs=IDLE, torso=STAND),
    Sequence('run',      6, 1, legs=Cycle('LEGS_RUN'), torso=STAND),
    Sequence('attack',   8, 1, legs=IDLE, torso=Play('TORSO_ATTACK', then='TORSO_STAND')),
    Sequence('pain1',    4, 2, legs=IDLE, torso=STAND, twitch=('roll', 20)),
    Sequence('pain2',    4, 2, legs=IDLE, torso=STAND, twitch=('roll', -20)),
    Sequence('pain3',    4, 2, legs=IDLE, torso=Fit('TORSO_RAISE')),
    Sequence('jump',     6, 1, legs=Concat((2, Fit('LEGS_JUMP')), (4, Fit('LEGS_LAND'))), torso=STAND),
    Sequence('flip',    12, 2, legs=IDLE, torso=Fit('TORSO_GESTURE', team_arena='TORSO_NEGATIVE')),
    Sequence('salute',  11, 2, legs=IDLE, torso=Fit('TORSO_GESTURE', team_arena='TORSO_AFFIRMATIVE')),
    Sequence('taunt',   17, 2, legs=IDLE, torso=Fit('TORSO_GESTURE')),
    Sequence('wave',    11, 2, legs=IDLE, torso=Fit('TORSO_GESTURE', team_arena='TORSO_FOLLOWME')),
    Sequence('point',   12, 2, legs=IDLE, torso=Fit('TORSO_GESTURE', team_arena='TORSO_GETFLAG')),
    Sequence('crstnd',  19, 2, legs=IDLECR, torso=STAND),
    Sequence('crwalk',   6, 1, legs=Cycle('LEGS_WALKCR'), torso=STAND),
    Sequence('crattak',  9, 1, legs=IDLECR, torso=Play('TORSO_ATTACK', then='TORSO_STAND')),
    Sequence('crpain',   4, 1, legs=IDLECR, torso=Fit('TORSO_RAISE')),
    Sequence('crdeath',  5, 1, both=Fit('BOTH_DEATH1'), blend_from=(IDLECR, STAND), blend_frames=2),
    Sequence('death1',   6, 2, both=Fit('BOTH_DEATH1')),
    Sequence('death2',   6, 2, both=Fit('BOTH_DEATH2')),
    Sequence('death3',   8, 2, both=Fit('BOTH_DEATH3')),
]

NUM_FRAMES = sum(s.count for s in SEQUENCES)
assert NUM_FRAMES == 198


def frame_table():
    """[(frame name, sequence, index within sequence)] for all 198 frames."""
    out = []
    for seq in SEQUENCES:
        for i, name in enumerate(seq.frame_names()):
            out.append((name, seq, i))
    return out
