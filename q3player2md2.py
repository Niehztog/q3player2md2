#!/usr/bin/env python3
"""Convert Quake III Arena player models into Quake II player models.

    q3player2md2.py --q3 ~/q2-dev/baseq3 --q2 ~/q2-dev/yquake2/release_/baseq2 sarge

writes out/players/sarge/{tris.md2,weapon.md2,w_*.md2,*.pcx,*.tga,*.wav}.
"""

import argparse
import os
import sys
import traceback

from q3p2m import convert, vfs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('models', nargs='*', help='Q3 model names (models/players/<name>)')
    ap.add_argument('--q3', action='append', required=True, metavar='PATH',
                    help='Q3 data: a baseq3 directory, a .pk3, or a directory of loose files; '
                         'repeatable, later ones override earlier ones')
    ap.add_argument('--q2', action='append', required=True, metavar='PATH',
                    help='Q2 data (baseq2 directory or .pak): palette and weapon models; repeatable')
    ap.add_argument('-o', '--out', default='out', help='output directory (default: out)')
    ap.add_argument('--name', help='Q2 model name (default: the Q3 name); one model only')
    ap.add_argument('--scale', type=float, default=0.9,
                    help='size relative to the Q3 model, feet stay on the floor (default 0.9)')
    ap.add_argument('--all', action='store_true', help='convert every Q3 player model found')
    ap.add_argument('--no-vwep', action='store_true', help='write weapon.md2 only, no w_*.md2')
    ap.add_argument('--no-sounds', action='store_true', help='do not copy player sounds')
    ap.add_argument('--preview', action='store_true',
                    help='render out/preview/<name>.png from the written files')
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    q3 = vfs.VFS()
    for p in args.q3:
        q3.add(os.path.expanduser(p))
    q2 = vfs.VFS()
    for p in args.q2:
        q2.add(os.path.expanduser(p))

    models = list(args.models)
    if args.all:
        models += sorted({n.split('/')[2] for n in q3.list('models/players/', '/animation.cfg')})
    if not models:
        ap.error('name at least one model, or use --all')
    if args.name and len(models) != 1:
        ap.error('--name needs exactly one model')

    failed = 0
    for model in models:
        print('== %s' % model)
        try:
            r = convert.convert(q3, q2, model, args.out, name=args.name, scale=args.scale,
                                vwep=not args.no_vwep, with_sounds=not args.no_sounds)
        except Exception as e:
            failed += 1
            print('   FAILED: %s' % e)
            if os.environ.get('Q3P2M_DEBUG'):
                traceback.print_exc()
            continue
        for line in r.lines:
            print('   ' + line)
        for w in r.warnings:
            print('   warning: ' + w)
        for p in r.problems:
            print('   PROBLEM: ' + p)
        failed += bool(r.problems)
        print('   -> %s' % r.out)
        if args.preview:
            from q3p2m import preview
            path = preview.contact_sheet(r.out, q2, os.path.join(args.out, 'preview'))
            print('   preview: %s' % path)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
