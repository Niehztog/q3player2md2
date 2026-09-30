# q3player2md2

Converts Quake III Arena and Team Arena player models into Quake II player models.

Input: `models/players/<name>/` with `lower.md3`, `upper.md3`, `head.md3`,
`animation.cfg` and the `*_<skin>.skin` files, read straight from `.pk3` files
or directories. A Team Arena character is a body without a head of its own
(`james`, `janet`) and a head from `models/players/heads/<name>/`.
Output: `players/<name>/` with `tris.md2` in Quake II's 198-frame player layout,
`weapon.md2` and `w_*.md2`, one skin per Q3 skin, icons, and sounds.

```sh
python3 q3player2md2.py --q3 ~/q2-dev/baseq3 --q2 ~/q2-dev/yquake2/release_/baseq2 sarge
python3 q3player2md2.py --q3 ~/q2-dev/baseq3 --q3 custom.pk3 --q2 ... custom --preview
python3 q3player2md2.py --q3 ~/q2-dev/baseq3 --q2 ... --all -o out
python3 q3player2md2.py --q3 ~/q2-dev/baseq3 --q3 ~/q2-dev/missionpack --q2 ... fritzkrieg pi neptune
```

Pass the Quake II mission packs' data as well (`--q2 .../baseq2 --q2 .../xatrix
--q2 .../rogue`) to get their weapons in the hand.

Then copy `out/players/<name>` into `baseq2/players/` and pick it in the player
setup menu, or `set skin <name>/default`.

| Option | |
|---|---|
| `--q3 PATH` | Q3 data: a `baseq3` directory, a `.pk3`, or loose files. Repeatable; later ones override earlier ones. |
| `--q2 PATH` | Q2 data (`baseq2` or `.pak`): the palette (`pics/colormap.pcx`) and the weapon models. Repeatable. |
| `-o DIR` | Output directory, default `out`. |
| `--name NAME` | Q2 model name, default the Q3 name. |
| `--head HEAD` | Team Arena head for the body, from `models/players/heads/<head>/`; also the default Q2 name. Team Arena's own characters need no `--head`: `neptune` is found in `teaminfo.txt`. |
| `--scale F` | Size relative to the Q3 model, feet stay on the floor. Default 0.9. |
| `--all` | Convert every Q3 player model found, and Team Arena's characters. |
| `--no-vwep` | Only `weapon.md2`, no per-weapon models. |
| `--no-sounds` | Do not copy sounds. |
| `--preview` | Render `out/preview/<name>.png` from the written files. |

Needs Python 3 with NumPy and Pillow.

## Output

| File | |
|---|---|
| `tris.md2` | 198 frames, standard Q2 frame names (`stand01` ... `death308`) |
| `<skin>.pcx` | one per Q3 skin, 8-bit, Q2 palette, at most 640x480 |
| `<skin>.tga` | the same skin in true colour, same layout; q2pro and yquake2 load it in place of the PCX |
| `<skin>_i.pcx`, `_i.tga` | 32x32 icon, from `icon_<skin>.tga` |
| `ctf_r`, `ctf_b` | copies of the `red` and `blue` skins, which Q2 CTF forces on its teams |
| `<team>`, `<team>_red`, `<team>_blue` | Team Arena's team skins (`stroggs`, `thefallen_red`, ...) |
| `weapon.md2`, `w_*.md2` | Q2 weapon models held in the hand, same 198 frames |
| `*.wav` | Q3 sounds under the names Q2 looks up in the model directory |

Q2 clients (id's, yquake2, q2pro) only accept a player model when the skin, the
icon, `tris.md2` and `weapon.md2` all load; otherwise they show male/grunt.

## How it works, and why this way

### A command-line tool, not Blender

hypov8's `q3_to_kp.py` converts Q3 players to Kingpin inside Blender, using
hypov8's MD3 importer and MD2/MDX exporter. Those add-ons are tested with
Blender 2.79 to 3.2 only, and every conversion is a series of clicks.
Nothing in this conversion needs an editor: it is tag arithmetic, resampling
animation timing, and image packing. As a plain Python program it runs
headless, converts all models in one go and gives the same result every time.
The output can still be touched up in Blender with hypov8's MD2 add-on.

### Putting the three parts together

`bake.py` assembles the parts per frame the way Q3's cgame does: tags are
interpolated linearly with their axes renormalized (`R_LerpTag`), the torso
hangs on the legs' `tag_torso`, the head and weapon on the torso's
`tag_head` and `tag_weapon` (`CG_PositionRotatedEntityOnTag`). The legs stand at
the origin facing +X, like Q2 player models. The head always uses frame 0.

`animation.cfg` is read with Q3's rules (`CG_ParseAnimationFile`): the legs
frame numbers are shifted by the torso-only frames `lower.md3` does not
contain, negative frame counts play backwards, Team Arena entries are
optional, and frame times are Q3's integer milliseconds.

The model is scaled by 0.9 about the feet, as gildor2/Quake2 does
(`QUAKE3_PLAYER_SCALE`). That makes sarge 52 units tall standing and 38
crouched; Q2's male is 50 and 35.

### Which Q3 animation becomes which Q2 frame

Q2 has one mesh and one frame number per player, Q3 animates legs and torso
separately. As in `q3_to_kp.py`'s `Frames_KP` table, every Q2 sequence names a
legs and a torso animation; the pairings follow gildor2/Quake2's
`server/sv_anim.cpp`, which drives Q3 models from Q2 frames at run time. The
table is `q3p2m/mapping.py`:

| Q2 frames | Legs | Torso | Notes |
|---|---|---|---|
| stand 0-39 | LEGS_IDLE | TORSO_STAND | |
| run 40-45 | LEGS_RUN | TORSO_STAND | Q2 plays it for every direction |
| attack 46-53 | LEGS_IDLE | TORSO_ATTACK, then TORSO_STAND | native speed |
| pain1, pain2 | LEGS_IDLE | TORSO_STAND | Q3 has no pain animations; Q3's pain twitch instead (torso roll of 20 degrees, decaying) |
| pain3 62-65 | LEGS_IDLE | TORSO_RAISE | Q2 plays pain3 backwards to lower a weapon and forwards to raise one |
| jump 66-71 | LEGS_JUMP (1-2), LEGS_LAND (3-6) | TORSO_STAND | jump2 is held in the air |
| flip, salute, taunt, wave, point | LEGS_IDLE | TORSO_GESTURE | Team Arena gestures when `animation.cfg` has them |
| crstnd 135-153 | LEGS_IDLECR | TORSO_STAND | |
| crwalk 154-159 | LEGS_WALKCR | TORSO_STAND | |
| crattak 160-168 | LEGS_IDLECR | TORSO_ATTACK, then TORSO_STAND | |
| crpain 169-172 | LEGS_IDLECR | TORSO_RAISE | also the crouched weapon change |
| crdeath 173-177 | BOTH_DEATH1 | BOTH_DEATH1 | blends out of the crouch |
| death1-3 | BOTH_DEATH1-3 | BOTH_DEATH1-3 | last frame is the dead pose |

Timing: loops keep roughly their Q3 speed and fit a whole number of cycles
into the sequence, so Q2's own looping is seamless (at least four frames per
cycle). Gestures and deaths are fitted into their Q2 frame count, so the last
Q2 frame is the last Q3 frame. Attacks play at Q3 speed and then hold the
stand pose. Q2 advances a player one frame per 100 ms server frame.

### The mesh

- MD3 duplicates a vertex wherever the texture coordinates change. MD2 stores
  positions and texture coordinates separately, so vertices that share a
  position in every MD3 frame are welded (sarge: 799 to 409). The 29 retail
  models end up between 330 and 506 vertices, far below the 2048 limit.
- MD3 and MD2 use the same triangle winding (checked on the retail models'
  stored normals), so triangles are copied as they are.
- Surfaces whose Q3 shader has `cull disable` get a second, reversed copy of
  each triangle, since Q2 always culls back faces (bones, hunter's feathers,
  slash's skates).
- GL commands (strips and fans) are built with the algorithm from id's `qdata`.
  yquake2's GL renderers draw from them, q2pro and the software renderer from
  the triangle list.
- Frames are quantized to 8 bits per axis over each frame's bounds; normals map
  to the nearest of Q2's 162.

### Skins

An MD2 has one set of texture coordinates, so all skins share one layout.
Surfaces that show the same image in every skin share a region of the atlas;
each region covers the part of its image that is used, wrapping when the
coordinates leave 0..1. The atlas keeps the source resolution when it fits
Q2's PCX limit of 640x480 (yquake2 also rejects skins taller than 480) and
shrinks uniformly otherwise; the TGA then keeps full resolution in the same
layout. The packer prefers square atlases because id's GL renderer caps
textures at 256 on each side.

Q3 shaders are flattened to one static image: the stage carrying the model's
own texture is used; a texture alpha-blended over a lower stage is composited
onto it (sarge's `krusade` over fire), and over an environment map's average
colour (hunter's chrome `harpy`). `alphaFunc` stages become cut-outs.

Cut-outs behave differently per renderer: id's and yquake2's GL renderers
alpha-test skins, q2pro draws them opaque, software renderers draw palette
index 255 in its (pink) colour. The PCX marks cut-outs with index 255; the TGA
keeps alpha and fills the transparent pixels with neighbouring colours so
q2pro shows something sensible. A surface hidden in only some skins (hunter's
feathers in `harpy`) is transparent in those skins.

Skin files written for another directory layout are common; a texture that is
not found is looked for under its file name in the model's directory, and a
surface missing from a `.skin` file matches a unique entry that differs by a
suffix (both needed for id's own `tim` model). Paths are unquoted as Q3's
`CommaParse` does (Team Arena quotes the ones with a space, `"models/players/
james/the fallen/..."`), and a doubled slash counts as one (a Team Arena shader
maps `models/players/heads//ursula/ursula_e.tga`).

### Team Arena characters

A Team Arena character is a body and a head: `teaminfo.txt` lists name and
sex, and the body is James's for a male, Janet's for a female, as in
`ui_main.c`'s `Character_Parse`; `--all` converts them all, and each can be
named on the command line. The head is `models/players/heads/<name>/<name>.md3`,
which is also where Q3 looks for the head of a model that has none of its own
(`CG_RegisterClientModelname`), so `james` alone is James. Its skins are the
body's `lower_`/`upper_<skin>.skin` with the head's `head_<skin>.skin`, and its
icon is the head's, as `CG_FindClientModelFile` and `CG_FindClientHeadFile` find
them. The bodies' team skins in `<team>/` become `<team>`, `<team>_red` and
`<team>_blue`. Sounds come from the body, like the cgame's.

Team Arena's `scripts/models.shader` replaces baseq3's and changes the look of
anarki, crash, doom, hunter, major, razor, slash and xaero. Convert the retail
models from baseq3 alone to keep their Quake III look, and add the Team Arena
data only for Team Arena's own models.

### Weapons

`weapon.md2` and `w_*.md2` are Q2's world weapon models held at the torso's
`tag_weapon` in every frame, with the scale and offset gildor2/Quake2 uses for
the same purpose (`resource/res/baseq2/models/weapons/*.cfg` there). They keep
the world models' skins, so no textures are copied. The Reckoning and Ground
Zero weapons are written when their models are in the Q2 data; a missing
`w_*.md2` falls back to `weapon.md2` in the client.

CTF's grapple has no world model. id's own `male/w_grapple.md2` holds Q2's
unused flare gun (`models/weapons/g_flareg`, at scale 0.5 and in the same hand
pose as every other weapon), so `w_grapple.md2` does too. Its scale and
offset follow from where id put it relative to twelve other weapons whose male
`w_*.md2` are the world model moved into the hand: their hand frame agrees to
about a unit, and the grapple lands at offset (0, 0, -17), scale 0.45 against
the others' 0.5.

### Sounds

Q3's `sound/player/<model>/` sounds are copied under Q2's names (`death1-4`,
`fall1-2`, `gurp1-2`, `jump1`, `pain25_1` ... `pain100_2`). Missing ones come from
sarge or mynx, as in Q3; Q2's medium fall (`fall2`) uses `pain100_1`, as Q3 does.

## Checking the result

- Every written MD2 is read back and checked for the engine limits, index
  ranges, and that the GL commands reproduce the triangle list with the same
  winding. The retail `male/tris.md2` passes the same check.
- `--preview` renders the written files: the MD2 through the reader, the PCX
  through a decoder that walks the data like id's `LoadPCX`, colours through the
  Q2 palette, alpha test like id's GL renderer. Back faces showing through
  holes are drawn magenta; the box is Q2's player bounding box.
- `tools/q2pro-shots.sh` takes third-person screenshots in q2pro on a private
  Xvfb.
- All 29 retail Q3 models convert without problems. They were checked in
  q2pro (in game, third person), and sarge also in yquake2's player setup
  preview with the GL1 renderer (GL commands) and the software renderer (PCX).
- Team Arena's 13 (fritzkrieg, pi and the 11 characters) convert without
  warnings. neptune was checked in q2pro in third person holding each of the
  19 weapons of Quake II, The Reckoning, Ground Zero and CTF.

## Limits

- MD2 allows 2048 vertices and 4096 triangles; bigger models fail with a
  message and need decimating first.
- One mesh and one frame number: no legs turned towards the strafe direction,
  no torso following the aim (Q2 only tilts the whole model by a third of the
  pitch), no independent legs and torso timing. gildor2/Quake2 renders Q3
  models natively for that, with its own protocol.
- Shader effects (environment maps, glow, scrolling) do not survive the
  flattening to one image.
- The hand holds Q2's pickup models, not Q3's weapons.
- Q2 decides the gender for obituaries from the model name, not from
  `animation.cfg`'s `sex`.

## Credits and licence

GPL-2.0-or-later (see LICENSE). `q3p2m/anorms.py` is Quake II's `anorms.h`
(id Software, GPL). The animation pairings, the player scale and the weapon
placement come from gildor2/Quake2 (Konstantin Nosov, GPL); the approach of
combining legs and torso animations per target sequence from hypov8's
`q3_to_kp.py`; the GL command builder from id's `qdata`; the `animation.cfg`
and tag rules from ioquake3.
