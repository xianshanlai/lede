#!/usr/bin/env python3
"""Collect only finished, compressed J1900 disk images and public build metadata."""

import argparse
import hashlib
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    target = args.source / 'bin/targets/x86/64'
    images = sorted(target.glob('*squashfs-combined*.img.gz'))
    if not any(path.name.endswith('squashfs-combined-efi.img.gz') for path in images):
        raise RuntimeError('UEFI image was not produced')
    if not any(path.name.endswith('squashfs-combined.img.gz') for path in images):
        raise RuntimeError('Legacy BIOS image was not produced')
    args.output.mkdir(parents=True, exist_ok=True)
    for path in images:
        shutil.copy2(path, args.output / path.name)
    for pattern in ('*.manifest', '*.buildinfo'):
        for path in target.glob(pattern):
            shutil.copy2(path, args.output / path.name)
    checksums = []
    for path in sorted(args.output.glob('*.img.gz')):
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(block)
        checksums.append(f'{digest.hexdigest()}  {path.name}\n')
    (args.output / 'sha256sums').write_text(''.join(checksums), encoding='utf-8')
    print('Collected firmware: ' + ', '.join(path.name for path in images))


if __name__ == '__main__':
    main()
