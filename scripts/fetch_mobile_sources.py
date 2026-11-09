#!/usr/bin/env python3
"""Fetch immutable mobile sources and verify bytes before unpacking them."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from urllib.request import urlopen

LOCK = Path(__file__).resolve().parents[1] / 'mobile-sources.json'


def fetch(source, destination):
    if destination.exists():
        raise ValueError(f'Refusing to reuse potentially patched sources: {destination}')
    with tempfile.TemporaryDirectory(prefix='mobile-source-', dir=destination.parent) as temp:
        archive = Path(temp) / 'source.tar'
        checksum = hashlib.sha256()
        with urlopen(source['url'], timeout=120) as response, archive.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                checksum.update(chunk)
                out.write(chunk)
        if checksum.hexdigest() != source['sha256']:
            raise ValueError(f'Source checksum mismatch: {source["url"]}')
        tree = Path(temp) / 'tree'
        tree.mkdir()
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            roots = set()
            for item in members:
                path = PurePosixPath(item.name)
                if path.is_absolute() or '..' in path.parts or not path.parts:
                    raise ValueError('Unsafe source archive path')
                roots.add(path.parts[0])
                if item.issym() or item.islnk():
                    # The FFmpeg distribution contains relative symlinks.
                    target = PurePosixPath(item.linkname)
                    if target.is_absolute() or '..' in target.parts:
                        raise ValueError('Unsafe source archive link')
                elif not (item.isfile() or item.isdir()):
                    raise ValueError('Unexpected source archive entry')
            if len(roots) != 1:
                raise ValueError('Expected a single source root')
            tar.extractall(tree)
        (tree / roots.pop()).rename(destination)


def main():
    destination = Path(sys.argv[1]).resolve()
    sources = json.loads(LOCK.read_text())
    for name, source in sources.items():
        fetch(source, destination / name)
    shutil.copytree(destination / 'fast_float' / 'include',
                    destination / 'libplacebo' / '3rdparty' / 'fast_float' / 'include')
    shutil.copytree(destination / 'vulkan_headers' / 'include',
                    destination / 'libplacebo' / '3rdparty' / 'Vulkan-Headers' / 'include')


if __name__ == '__main__':
    main()
