"""Build the tris.md2 topology from the three parts and their baked frames.

MD3 duplicates a vertex wherever its texture coordinates change (seams).
MD2 indexes positions and texture coordinates separately, so vertices of a
part that sit at the same position in every MD3 frame are welded into one
MD2 position; this keeps well under the 2048 vertex limit and makes the
8-bit quantization treat both sides of a seam alike.
"""

import numpy as np

from . import md2
from .skins import PARTS


class Mesh:
    def __init__(self, parts, skinset, atlas):
        self.members = []           # (part, part vertex -> MD2 vertex or -1)
        self.num_xyz = 0
        tris_xyz, tris_st = [], []
        st_index = {}
        st_list = []
        self.dropped = 0
        self.doubled = 0
        for part in PARTS:
            p = parts[part]
            # weld: identical int16 xyz in every frame of this part
            raw = p.xyz_raw.transpose(1, 0, 2).reshape(p.xyz_raw.shape[1], -1)
            _, inverse = np.unique(raw, axis=0, return_inverse=True)
            inverse = inverse.reshape(-1)
            used = {}           # welded vertex -> MD2 vertex
            for si, surf in enumerate(p.model.surfaces):
                if not skinset.visible(part, si):
                    continue
                off = p.offsets[si]
                two_sided = skinset.two_sided(part, si)
                uv = atlas.remap(part, si, surf.st)
                st = np.rint(uv * [atlas.width, atlas.height]).astype(int)
                for tri in surf.tris:
                    xyz = []
                    for v in tri:
                        w = inverse[off + v]
                        if w not in used:
                            used[w] = self.num_xyz
                            self.num_xyz += 1
                        xyz.append(used[w])
                    if len(set(xyz)) < 3:
                        self.dropped += 1
                        continue
                    sts = []
                    for v in tri:
                        key = (int(st[v, 0]), int(st[v, 1]))
                        if key not in st_index:
                            st_index[key] = len(st_list)
                            st_list.append(key)
                        sts.append(st_index[key])
                    tris_xyz.append(xyz)
                    tris_st.append(sts)
                    if two_sided:
                        # Q2 always culls back faces: add the other side explicitly
                        tris_xyz.append([xyz[0], xyz[2], xyz[1]])
                        tris_st.append([sts[0], sts[2], sts[1]])
                        self.doubled += 1
            # every source vertex of this part -> MD2 vertex (or -1), for normal averaging
            to_md2 = np.array([used.get(w, -1) for w in inverse.tolist()], np.int64)
            self.members.append((part, to_md2))
        self.tris_xyz = np.array(tris_xyz, np.int32).reshape(-1, 3)
        self.tris_st = np.array(tris_st, np.int32).reshape(-1, 3)
        self.st = np.array(st_list, np.int32).reshape(-1, 2)

    def frame_arrays(self, baked):
        """BakedFrame -> positions (N, 3) and unit normals (N, 3)."""
        xyz = np.empty((self.num_xyz, 3), np.float32)
        nrm = np.zeros((self.num_xyz, 3), np.float32)
        for part, to_md2 in self.members:
            verts, normals = baked.parts[part]
            ok = to_md2 >= 0
            xyz[to_md2[ok]] = verts[ok]         # welded vertices share one position
            np.add.at(nrm, to_md2[ok], normals[ok])
        length = np.linalg.norm(nrm, axis=1, keepdims=True)
        nrm /= np.where(length == 0, 1, length)
        return xyz, nrm

    def md2(self, baked_frames, skinwidth, skinheight, skins):
        frames = []
        for bf in baked_frames:
            xyz, nrm = self.frame_arrays(bf)
            frames.append(md2.Frame(bf.name, xyz, md2.nearest_normal(nrm)))
        return md2.Model(skinwidth, skinheight, skins, self.st, self.tris_xyz, self.tris_st, frames)
