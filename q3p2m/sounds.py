"""Q3 player sounds -> the Q2 "sexed" sounds the game looks up in players/<model>/.

Missing Q3 sounds fall back to sarge (male) or mynx (female), as Q3's cgame
does. Q2 fall2 is the medium fall, for which Q3 plays pain100_1.
"""

import os

# Q2 name: Q3 names to try, in order
SOUNDS = [
    ('death1.wav', ('death1.wav',)),
    ('death2.wav', ('death2.wav', 'death1.wav')),
    ('death3.wav', ('death3.wav', 'death1.wav')),
    ('death4.wav', ('death3.wav', 'death2.wav', 'death1.wav')),
    ('fall1.wav', ('fall1.wav',)),
    ('fall2.wav', ('pain100_1.wav', 'fall1.wav')),
    ('gurp1.wav', ('drown.wav', 'gasp.wav')),
    ('gurp2.wav', ('drown.wav', 'gasp.wav')),
    ('jump1.wav', ('jump1.wav',)),
    ('pain25_1.wav', ('pain25_1.wav',)),
    ('pain25_2.wav', ('pain25_1.wav',)),
    ('pain50_1.wav', ('pain50_1.wav', 'pain25_1.wav')),
    ('pain50_2.wav', ('pain50_1.wav', 'pain25_1.wav')),
    ('pain75_1.wav', ('pain75_1.wav', 'pain50_1.wav')),
    ('pain75_2.wav', ('pain75_1.wav', 'pain50_1.wav')),
    ('pain100_1.wav', ('pain100_1.wav', 'pain75_1.wav')),
    ('pain100_2.wav', ('pain100_1.wav', 'pain75_1.wav')),
]


def copy(vfs, model, sex, outdir):
    fallback = 'mynx' if sex == 'f' else 'sarge'
    written, missing = 0, []
    for q2name, candidates in SOUNDS:
        src = None
        for d in (model, fallback):
            for c in candidates:
                path = 'sound/player/%s/%s' % (d, c)
                if vfs.exists(path):
                    src = path
                    break
            if src:
                break
        if src is None:
            missing.append(q2name)
            continue
        with open(os.path.join(outdir, q2name), 'wb') as f:
            f.write(vfs.read(src))
        written += 1
    return written, missing
