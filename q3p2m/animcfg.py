"""Quake III animation.cfg parser, following CG_ParseAnimationFile in ioq3."""

ANIM_NAMES = [
    'BOTH_DEATH1', 'BOTH_DEAD1', 'BOTH_DEATH2', 'BOTH_DEAD2', 'BOTH_DEATH3', 'BOTH_DEAD3',
    'TORSO_GESTURE', 'TORSO_ATTACK', 'TORSO_ATTACK2', 'TORSO_DROP', 'TORSO_RAISE',
    'TORSO_STAND', 'TORSO_STAND2',
    'LEGS_WALKCR', 'LEGS_WALK', 'LEGS_RUN', 'LEGS_BACK', 'LEGS_SWIM', 'LEGS_JUMP',
    'LEGS_LAND', 'LEGS_JUMPB', 'LEGS_LANDB', 'LEGS_IDLE', 'LEGS_IDLECR', 'LEGS_TURN',
    # Team Arena
    'TORSO_GETFLAG', 'TORSO_GUARDBASE', 'TORSO_PATROL', 'TORSO_FOLLOWME',
    'TORSO_AFFIRMATIVE', 'TORSO_NEGATIVE',
]
MAX_ANIMATIONS = len(ANIM_NAMES)
IDX = {n: i for i, n in enumerate(ANIM_NAMES)}
FIRST_TA = IDX['TORSO_GETFLAG']


class Animation:
    def __init__(self, first, num, loop, fps, reversed_):
        self.first = first
        self.num = num
        self.loop = loop
        self.fps = fps
        self.reversed = reversed_
        # Q3 keeps an integer frameLerp in milliseconds; timing follows that.
        self.frame_time = int(1000 / fps) / 1000.0 or 0.001

    def __repr__(self):
        return 'Animation(first=%d, num=%d, loop=%d, fps=%g%s)' % (
            self.first, self.num, self.loop, self.fps, ', reversed' if self.reversed else '')


class AnimationConfig:
    def __init__(self):
        self.anims = {}         # name -> Animation
        self.sex = 'm'
        self.has_team_arena = False
        self.fixedlegs = False
        self.fixedtorso = False

    def __getitem__(self, name):
        return self.anims[name]


def tokens(text):
    """COM_Parse: whitespace-separated tokens, // and /* */ comments, "quoted" strings."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c == '"':
            j = text.find('"', i + 1)
            j = n if j < 0 else j
            yield text[i + 1:j]
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and not text.startswith('//', j):
                j += 1
            yield text[i:j]
            i = j


def _atoi(s):
    digits = ''
    for k, ch in enumerate(s):
        if ch.isdigit() or (k == 0 and ch in '+-'):
            digits += ch
        else:
            break
    try:
        return int(digits)
    except ValueError:
        return 0


def _atof(s):
    try:
        return float(s)
    except ValueError:
        return float(_atoi(s))


def parse(text, name='animation.cfg'):
    cfg = AnimationConfig()
    toks = list(tokens(text))
    pos = 0
    while pos < len(toks):
        t = toks[pos]
        low = t.lower()
        if t[:1].isdigit() or t[:1] == '-':
            break
        pos += 1
        if low == 'footsteps':
            pos += 1
        elif low == 'headoffset':
            pos += 3
        elif low == 'sex':
            if pos < len(toks):
                cfg.sex = toks[pos][:1].lower() or 'm'
            pos += 1
        elif low == 'fixedlegs':
            cfg.fixedlegs = True
        elif low == 'fixedtorso':
            cfg.fixedtorso = True
        # unknown tokens are skipped, as Q3 does

    anims = [None] * MAX_ANIMATIONS
    skip = 0
    i = 0
    while i < MAX_ANIMATIONS:
        if pos + 4 > len(toks):
            break
        first = _atoi(toks[pos])
        num = _atoi(toks[pos + 1])
        loop = _atoi(toks[pos + 2])
        fps = _atof(toks[pos + 3])
        pos += 4
        if i == IDX['LEGS_WALKCR']:
            skip = first - anims[IDX['TORSO_GESTURE']].first
        if IDX['LEGS_WALKCR'] <= i < FIRST_TA:
            first -= skip
        rev = num < 0
        num = abs(num)
        if fps == 0:
            fps = 1
        anims[i] = Animation(first, num, loop, fps, rev)
        i += 1

    if i < FIRST_TA:
        raise ValueError('%s: only %d of %d animations' % (name, i, FIRST_TA))
    cfg.has_team_arena = i == MAX_ANIMATIONS
    for k in range(i, MAX_ANIMATIONS):
        g = anims[IDX['TORSO_GESTURE']]
        anims[k] = Animation(g.first, g.num, g.loop, g.fps, False)

    for k, a in enumerate(anims):
        cfg.anims[ANIM_NAMES[k]] = a
    walkcr, walk = cfg.anims['LEGS_WALKCR'], cfg.anims['LEGS_WALK']
    cfg.anims['LEGS_BACKCR'] = Animation(walkcr.first, walkcr.num, walkcr.loop, walkcr.fps, True)
    cfg.anims['LEGS_BACKWALK'] = Animation(walk.first, walk.num, walk.loop, walk.fps, True)
    return cfg
