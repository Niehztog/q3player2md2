"""Just enough of Quake III's shader scripts to find a surface's base texture.

Player shaders often wrap the texture: a $whiteimage stage lit by
lightingDiffuse with the texture blended over it (xaero), a glow stage on top
(sarge's cigar), or the texture alpha-blended over a scrolling effect (sarge's
krusade skin). A Q2 skin can hold only one static image, so this picks the
stage that carries the model's own texture and notes whether it needs an
alpha cutout or an underlay to be flattened onto.
"""

import os

IMAGE_EXTENSIONS = ('.tga', '.jpg', '.jpeg', '.png')
NODRAW_NAMES = {'nodraw', 'textures/common/nodraw', 'common/nodraw', 'textures/common/invisible'}


class Stage:
    def __init__(self):
        self.map = None
        self.blend = None       # (src, dst) lowercase
        self.alphafunc = None
        self.tcgen = None
        self.tcscale = (1.0, 1.0)


class Shader:
    def __init__(self, name):
        self.name = name
        self.stages = []
        self.nodraw = False
        self.two_sided = False


class TextureRef:
    def __init__(self, image=None, nodraw=False, alpha_test=False, underlay=None, missing=None,
                 two_sided=False):
        self.image = image              # VFS path of the image, or None
        self.two_sided = two_sided      # Q3 draws it without back-face culling
        self.nodraw = nodraw
        self.alpha_test = alpha_test
        self.underlay = underlay        # (image path, (scale_s, scale_t), is env map) or None
        self.missing = missing          # name that could not be found
        self.relocated = None           # original name, when found elsewhere

    def key(self):
        return (self.image, self.alpha_test, self.underlay, self.missing)


def _lines(text):
    """Tokens grouped by line, comments removed."""
    out = []
    in_block = False
    for line in text.splitlines():
        toks = []
        i, n = 0, len(line)
        while i < n:
            if in_block:
                j = line.find('*/', i)
                if j < 0:
                    i = n
                    continue
                in_block = False
                i = j + 2
                continue
            if line.startswith('//', i):
                break
            if line.startswith('/*', i):
                in_block = True
                i += 2
                continue
            if line[i].isspace():
                i += 1
                continue
            if line[i] == '"':
                j = line.find('"', i + 1)
                j = n if j < 0 else j
                toks.append(line[i + 1:j])
                i = j + 1
                continue
            j = i
            while j < n and not line[j].isspace():
                j += 1
            toks.append(line[i:j])
            i = j
        if toks:
            out.append(toks)
    return out


def parse(text, shaders):
    lines = _lines(text)
    i = 0
    while i < len(lines):
        toks = lines[i]
        i += 1
        if toks == ['{'] or toks == ['}']:
            continue
        name = toks[0].lower()
        if len(toks) > 1 and toks[1] == '{':
            pass
        elif i < len(lines) and lines[i][0] == '{':
            i += 1
        else:
            continue
        sh = Shader(name)
        depth = 1
        stage = None
        while i < len(lines) and depth > 0:
            t = lines[i]
            i += 1
            head = t[0].lower()
            if head == '{':
                depth += 1
                stage = Stage()
                sh.stages.append(stage)
            elif head == '}':
                depth -= 1
                stage = None
            elif stage is None:
                arg = t[1].lower() if len(t) > 1 else ''
                if head == 'surfaceparm' and arg == 'nodraw':
                    sh.nodraw = True
                elif head == 'cull' and arg in ('none', 'disable', 'twosided'):
                    sh.two_sided = True
            else:
                args = [a.lower() for a in t[1:]]
                if head in ('map', 'clampmap') and args:
                    stage.map = t[1]
                elif head == 'animmap' and len(args) > 1:
                    stage.map = t[2]
                elif head == 'blendfunc' and args:
                    if len(args) == 1:
                        stage.blend = {'add': ('gl_one', 'gl_one'),
                                       'filter': ('gl_dst_color', 'gl_zero'),
                                       'blend': ('gl_src_alpha', 'gl_one_minus_src_alpha')}.get(args[0])
                    else:
                        stage.blend = (args[0], args[1])
                elif head == 'alphafunc' and args:
                    stage.alphafunc = args[0]
                elif head == 'tcgen' and args:
                    stage.tcgen = args[0]
                elif head == 'tcmod' and len(args) >= 3 and args[0] == 'scale':
                    try:
                        stage.tcscale = (float(args[1]), float(args[2]))
                    except ValueError:
                        pass
        shaders.setdefault(name, sh)


def load_all(vfs):
    shaders = {}
    for path in vfs.list('scripts/', '.shader'):
        parse(vfs.read(path).decode('latin1'), shaders)
    return shaders


def _strip(name):
    return os.path.splitext(name.replace('\\', '/').lower())[0]


def _real_map(stage):
    return stage.map and not stage.map.startswith('$') and stage.map.lower() != '*white'


def resolve(name, vfs, shaders, model_dir=None):
    """Shader or image name from a .skin file or an MD3 surface -> TextureRef.

    Model packs often point at the author's own directory layout; an image
    that is not found is looked for again under its file name in model_dir."""
    ref = _resolve(name, vfs, shaders)
    if ref.missing and model_dir and ref.missing != '(empty)':
        alt = model_dir + os.path.basename(ref.missing.replace('\\', '/'))
        if alt.lower() != ref.missing.lower():
            again = _resolve(alt, vfs, shaders)
            if not again.missing:
                again.relocated = ref.missing
                return again
    return ref


def _resolve(name, vfs, shaders):
    if not name:
        return TextureRef(missing='(empty)')
    key = _strip(name)
    if key in NODRAW_NAMES:
        return TextureRef(nodraw=True)
    sh = shaders.get(key)
    if sh is not None:
        if sh.nodraw or not sh.stages:
            return TextureRef(nodraw=True)
        stages = [s for s in sh.stages if _real_map(s)]
        base = next((s for s in stages if _strip(s.map) == key), None)
        if base is None:
            base = next((s for s in stages if s.tcgen != 'environment'), None)
        if base is None and stages:
            base = stages[0]
        if base is not None:
            image = vfs.find(base.map, IMAGE_EXTENSIONS)
            if image is None:
                return TextureRef(missing=base.map)
            underlay = None
            if base.blend == ('gl_src_alpha', 'gl_one_minus_src_alpha'):
                earlier = sh.stages[:sh.stages.index(base)]
                under = next((s for s in reversed(earlier) if _real_map(s)), None)
                under_image = under and vfs.find(under.map, IMAGE_EXTENSIONS)
                if under_image:
                    underlay = (under_image, under.tcscale, under.tcgen == 'environment')
            return TextureRef(image=image, alpha_test=base.alphafunc is not None, underlay=underlay,
                              two_sided=sh.two_sided)
    image = vfs.find(name, IMAGE_EXTENSIONS)
    if image is None:
        return TextureRef(missing=name)
    return TextureRef(image=image)
