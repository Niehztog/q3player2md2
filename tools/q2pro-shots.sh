#!/bin/sh
# Screenshot converted player models in q2pro without a display.
#
#   tools/q2pro-shots.sh Q2PRO GAMELIB BASEQ2 PLAYERS OUTDIR model/skin [model/skin ...]
#
# Q2PRO    q2pro client binary
# GAMELIB  its game library (game<cpu>.so)
# BASEQ2   Quake II data with the retail pak files (players/male is used when present)
# PLAYERS  directory holding the converted <model>/ directories
# OUTDIR   where the screenshots go, one per model/skin, in third person
#
# Runs on a private Xvfb with q2pro's x11 driver: without vid_driver x11 q2pro
# picks its Wayland driver and opens on the desktop session instead.
# dmflags 512 (spawn farthest) with nobody else on the map always picks the
# same spawn point, so runs can be compared.
set -e
[ $# -ge 6 ] || { sed -n '3,15p' "$0"; exit 2; }
q2pro=$(realpath "$1"); gamelib=$(realpath "$2"); baseq2=$(realpath "$3")
players=$(realpath "$4"); out=$5
shift 5

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/baseq2/players" "$work/home"
for p in "$baseq2"/*.pak; do ln -s "$p" "$work/baseq2/"; done
[ -d "$baseq2/players/male" ] && ln -s "$baseq2/players/male" "$work/baseq2/players/male"
for m in "$players"/*/; do ln -sfn "$(realpath "$m")" "$work/baseq2/players/"; done
cp "$gamelib" "$work/baseq2/"

{
    echo 'set gl_screenshot_format png'
    echo 'set cl_thirdperson 1'
    echo 'set cl_thirdperson_range 70'
    echo 'set cl_thirdperson_angle 160'
    echo 'set crosshair 0'
    echo "set skin $1"
    echo 'map q2dm1'
    echo 'wait 300'
    for s in "$@"; do
        echo "set skin $s"
        echo 'wait 60'
        echo 'screenshot'
    done
    echo 'quit'
} > "$work/baseq2/shots.cfg"

env -u WAYLAND_DISPLAY xvfb-run -a -s "-screen 0 1024x768x24" "$q2pro" \
    +set vid_driver x11 +set basedir "$work" +set homedir "$work/home" +set libdir "$work" \
    +set vid_fullscreen 0 +set vid_geometry 800x600 +set s_enable 0 \
    +set deathmatch 1 +set dmflags 512 +set cheats 1 +exec shots.cfg > "$work/q2pro.log" 2>&1 || true

mkdir -p "$out"
i=0
for s in "$@"; do
    src=$(printf '%s/home/baseq2/screenshots/quake%03d.png' "$work" $i)
    if [ -f "$src" ]; then
        cp "$src" "$out/$(echo "$s" | tr / _).png"
        echo "$out/$(echo "$s" | tr / _).png"
    else
        echo "no screenshot for $s (see q2pro output below)" >&2
        tail -20 "$work/q2pro.log" >&2
    fi
    i=$((i + 1))
done
