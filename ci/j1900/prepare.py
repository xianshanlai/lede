#!/usr/bin/env python3
"""Prepare an isolated LEDE checkout using only committed, generic inputs."""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(*args, cwd=None):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def revision(path):
    return subprocess.check_output(
        ['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True
    ).strip()


def read_config(path):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        enabled = re.fullmatch(r'(CONFIG_[\w-]+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_[\w-]+) is not set', line)
        if enabled:
            values[enabled[1]] = enabled[2]
        elif disabled:
            values[disabled[1]] = 'n'
    return values


def check_inputs():
    lock = json.loads((HERE / 'sources.lock.json').read_text(encoding='utf-8'))
    repositories = [lock['lede'], lock['openclash'], *lock['feeds'].values()]
    for item in repositories:
        if not re.fullmatch(r'[a-f0-9]{40}', item['commit']):
            raise ValueError('Every repository must be pinned to a complete commit')
        if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+\.git', item['repository']):
            raise ValueError('Unexpected repository URL')
    for name in lock['feeds']:
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise ValueError('Invalid feed name')
    core = lock['mihomo']
    if not re.fullmatch(r'[a-f0-9]{64}', core['sha256']):
        raise ValueError('Mihomo must have a SHA256 checksum')
    expected_url = (
        'https://github.com/MetaCubeX/mihomo/releases/download/'
        f"{core['version']}/mihomo-linux-amd64-v1-{core['version']}.gz"
    )
    if core['url'] != expected_url:
        raise ValueError('J1900 requires the baseline amd64-v1 core')
    seed = read_config(HERE / 'config.seed')
    assert seed['CONFIG_TARGET_x86_64'] == 'y'
    assert seed['CONFIG_PACKAGE_samba4-server'] == 'y'
    assert seed['CONFIG_PACKAGE_ksmbd-server'] == 'n'
    assert seed['CONFIG_PACKAGE_automount'] == 'n'
    assert seed['CONFIG_PACKAGE_luci-app-vlmcsd'] == 'y'
    assert seed['CONFIG_TARGET_ROOTFS_PARTSIZE'] == '1024'
    print('Locked sources, baseline core and generic profile validated.', flush=True)
    return lock, seed


def fetch(item, destination):
    if destination.exists():
        raise RuntimeError(f'Refusing to reuse a non-empty source path: {destination}')
    destination.mkdir(parents=True)
    run('git', 'init', '-q', destination)
    run('git', '-C', destination, 'remote', 'add', 'origin', item['repository'])
    run('git', '-C', destination, 'fetch', '--depth=1', 'origin', item['commit'])
    run('git', '-C', destination, 'checkout', '--detach', 'FETCH_HEAD')
    if revision(destination) != item['commit']:
        raise RuntimeError('Downloaded source revision does not match its lock')


def install_core(source, core):
    download = source / 'dl' / ('mihomo-amd64-v1-' + core['version'] + '.gz')
    download.parent.mkdir(parents=True, exist_ok=True)
    run('curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '20',
        '--max-time', '180', '--output', download, core['url'])
    if hashlib.sha256(download.read_bytes()).hexdigest() != core['sha256']:
        raise RuntimeError('Mihomo SHA256 verification failed')
    binary = source / 'files/etc/openclash/core/clash_meta'
    binary.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(download, 'rb') as incoming, binary.open('wb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    binary.chmod(0o755)
    with binary.open('rb') as handle:
        header = handle.read(20)
    if header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != 62:
        raise RuntimeError('Core is not a little-endian x86-64 ELF executable')
    version = subprocess.check_output([str(binary), '-v'], text=True).strip()
    if core['version'] not in version:
        raise RuntimeError('Mihomo executable version does not match its lock')
    print(version, flush=True)
    return version


def prepare(source, lock, requested):
    source = source.resolve()
    if revision(source) != lock['lede']['commit']:
        raise RuntimeError('LEDE checkout does not match sources.lock.json')
    if (source / 'files').exists() and any((source / 'files').iterdir()):
        raise RuntimeError('An existing firmware overlay must be reviewed before building')
    buildinfo = ROOT / 'artifacts/buildinfo'
    buildinfo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / 'sources.lock.json', buildinfo)
    shutil.copy2(HERE / 'config.seed', buildinfo)

    feed_lines = []
    for name, item in lock['feeds'].items():
        fetch(item, source / 'feeds' / name)
        feed_lines.append(f"src-git {name} {item['repository']}^{item['commit']}\n")
    (source / 'feeds.conf.default').write_text(''.join(feed_lines), encoding='utf-8')
    plugin_source = source / '.ci-sources/openclash'
    fetch(lock['openclash'], plugin_source)
    plugin_destination = source / 'package/custom/luci-app-openclash'
    shutil.copytree(plugin_source / 'luci-app-openclash', plugin_destination)

    # Existing shallow feed checkouts plus commit-pinned URLs avoid moving branches.
    run('./scripts/feeds', 'update', '-a', cwd=source)
    run('./scripts/feeds', 'install', '-a', cwd=source)
    shutil.copytree(HERE / 'files', source / 'files', dirs_exist_ok=True)
    for path in (source / 'files').rglob('*'):
        if path.is_file():
            path.chmod(0o755 if path.read_bytes().startswith(b'#!') else 0o644)
    core_version = install_core(source, lock['mihomo'])
    shutil.copy2(HERE / 'config.seed', source / '.config')
    run('make', 'defconfig', cwd=source)
    shutil.copy2(source / '.config', buildinfo / 'config.full')
    shutil.copy2(source / 'feeds.conf.default', buildinfo)
    resolved = read_config(source / '.config')
    mismatches = []
    for name, expected in requested.items():
        actual = resolved.get(name, 'n')
        if actual != expected:
            mismatches.append(f'{name}: requested {expected}, resolved {actual}')
    if mismatches:
        raise RuntimeError('Configuration symbols changed or dependencies are missing:\n'
                           + '\n'.join(mismatches))
    metadata = {
        'lede': revision(source),
        'feeds': {name: revision(source / 'feeds' / name) for name in lock['feeds']},
        'openclash': revision(plugin_source),
        'mihomo': core_version,
        'source_date_epoch': subprocess.check_output(
            ['git', '-C', str(source), 'log', '-1', '--format=%ct'], text=True
        ).strip(),
        'workflow_commit': os.environ.get('GITHUB_SHA', 'local'),
    }
    (buildinfo / 'source-revisions.json').write_text(
        json.dumps(metadata, indent=2) + '\n', encoding='utf-8'
    )
    print('Resolved configuration matches every explicitly requested setting.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path)
    parser.add_argument('--check-inputs', action='store_true')
    args = parser.parse_args()
    lock, requested = check_inputs()
    if not args.check_inputs:
        if args.source is None:
            parser.error('--source is required when preparing a build')
        prepare(args.source, lock, requested)


if __name__ == '__main__':
    main()
