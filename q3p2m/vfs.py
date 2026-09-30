"""Read-only, case-insensitive file system over directories, .pk3/.zip and .pak files.

Sources added later override sources added earlier. Inside a directory the
archives override loose files, as they do in both engines' search paths.
"""

import os
import struct
import zipfile


class VFS:
    def __init__(self):
        self._files = {}        # lowercase path -> (reader, label)
        self.sources = []

    # ------------------------------------------------------------------ adding

    def add(self, path):
        if os.path.isdir(path):
            self._add_dir(path)
            archives = sorted(f for f in os.listdir(path)
                              if f.lower().endswith(('.pk3', '.pak', '.zip')))
            for name in archives:
                self._add_archive(os.path.join(path, name))
        elif os.path.isfile(path):
            self._add_archive(path)
        else:
            raise FileNotFoundError(path)

    def _add_dir(self, root):
        self.sources.append(root)
        for dirpath, _, files in os.walk(root, followlinks=True):
            for f in files:
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root).replace(os.sep, '/')
                self._files[rel.lower()] = (lambda p=full: _read_range(p, 0, -1), full)

    def _add_archive(self, path):
        with open(path, 'rb') as f:
            magic = f.read(4)
        if magic == b'PACK':
            self._add_pak(path)
        elif zipfile.is_zipfile(path):
            self._add_zip(path)
        else:
            raise ValueError('%s: neither a directory, a zip/pk3 nor a pak file' % path)

    def _add_zip(self, path):
        self.sources.append(path)
        z = zipfile.ZipFile(path)
        for info in z.infolist():
            if not info.is_dir():
                self._files[info.filename.lower()] = (
                    lambda n=info.filename: z.read(n), '%s:%s' % (path, info.filename))

    def _add_pak(self, path):
        self.sources.append(path)
        with open(path, 'rb') as f:
            _, ofs, length = struct.unpack('<4sii', f.read(12))
            f.seek(ofs)
            directory = f.read(length)
        for i in range(0, length, 64):
            name = directory[i:i + 56].split(b'\0')[0].decode('latin1')
            pos, size = struct.unpack('<ii', directory[i + 56:i + 64])
            self._files[name.lower()] = (
                lambda p=pos, s=size: _read_range(path, p, s), '%s:%s' % (path, name))

    # ----------------------------------------------------------------- queries

    def exists(self, name):
        return name.lower() in self._files

    def read(self, name):
        try:
            return self._files[name.lower()][0]()
        except KeyError:
            raise FileNotFoundError(name) from None

    def where(self, name):
        return self._files[name.lower()][1]

    def list(self, prefix='', suffix=''):
        prefix, suffix = prefix.lower(), suffix.lower()
        return sorted(n for n in self._files if n.startswith(prefix) and n.endswith(suffix))

    def find(self, name, extensions):
        """Return the first existing variant of name with one of the extensions."""
        if self.exists(name):
            return name
        base = os.path.splitext(name)[0]
        for ext in extensions:
            if self.exists(base + ext):
                return base + ext
        return None


def _read_range(path, pos, size):
    with open(path, 'rb') as f:
        f.seek(pos)
        return f.read(size)
