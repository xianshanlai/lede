#!/usr/bin/env python3
"""Resolve moving branches once, then build only the recorded immutable revisions."""

import argparse
import base64
import copy
import datetime
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMIT = re.compile(r'[a-f0-9]{40}')


def github_repository(url):
    match = re.fullmatch(r'https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?', url)
    if not match:
        raise ValueError(f'Expected a GitHub HTTPS repository: {url}')
    return match[1]


def github_api(endpoint):
    return json.loads(subprocess.check_output(
        ['gh', 'api', endpoint], text=True, encoding='utf-8', timeout=90
    ))


def resolve_ref(repository, branch=None):
    github_repository(repository)
    reference = f'refs/heads/{branch}' if branch else 'HEAD'
    output = subprocess.check_output(
        ['git', 'ls-remote', '--exit-code', '--symref', repository, reference],
        text=True, encoding='utf-8', timeout=90,
    )
    resolved_branch = branch
    commit = None
    for line in output.splitlines():
        value, name = line.split('\t', 1)
        if name != reference:
            continue
        if value.startswith('ref: refs/heads/'):
            resolved_branch = value.removeprefix('ref: refs/heads/')
        elif COMMIT.fullmatch(value):
            commit = value
    if not commit or not resolved_branch:
        raise RuntimeError(f'Unable to resolve {repository} branch {branch or "HEAD"}')
    print(f'{repository} [{resolved_branch}] -> {commit}', flush=True)
    return {'repository': repository, 'branch': resolved_branch, 'commit': commit}


def declared_feeds(content, allowed=None):
    result = {}
    for line in content.splitlines():
        fields = shlex.split(line, comments=True)
        if len(fields) < 3 or fields[0] not in ('src-git', 'src-git-full'):
            continue
        if allowed is not None and fields[1] not in allowed:
            continue
        location, separator, commit = fields[2].partition('^')
        repository, _, branch = location.partition(';')
        github_repository(repository)
        if not repository.endswith('.git'):
            repository += '.git'
        if separator and not COMMIT.fullmatch(commit):
            raise ValueError('An upstream-pinned feed must use a complete commit')
        result[fields[1]] = {
            'repository': repository, 'branch': branch or None,
            'commit': commit if separator else None,
        }
    return result


def latest_mihomo():
    release = github_api('repos/MetaCubeX/mihomo/releases/latest')
    version = release['tag_name']
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('Expected a stable Mihomo release')
    if not re.fullmatch(r'v\d+\.\d+\.\d+', version):
        raise ValueError('Unexpected Mihomo version tag')
    name = f'mihomo-linux-amd64-v1-{version}.gz'
    asset = next((item for item in release['assets'] if item['name'] == name), None)
    if asset is None:
        raise RuntimeError('Latest Mihomo release has no J1900-compatible amd64-v1 asset')
    digest = asset.get('digest') or ''
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise RuntimeError('Latest Mihomo asset does not provide a SHA256 digest')
    expected_url = f'https://github.com/MetaCubeX/mihomo/releases/download/{version}/{name}'
    if asset['browser_download_url'] != expected_url:
        raise ValueError('Unexpected Mihomo download URL')
    print(f'Mihomo stable release -> {version} (amd64-v1)', flush=True)
    return {'version': version, 'url': expected_url, 'sha256': digest.removeprefix('sha256:')}


def resolve_lock(template, mode, source_repository):
    lock = copy.deepcopy(template)
    if mode == 'latest':
        if source_repository == 'upstream':
            repository = template['lede']['upstream_repository']
        else:
            repository = template['lede'].get('fork_repository', template['lede']['repository'])
        lock['lede'].update(resolve_ref(repository, template['lede'].get('branch', 'master')))
        repo = github_repository(repository)
        response = github_api(
            f"repos/{repo}/contents/feeds.conf.default?ref={lock['lede']['commit']}"
        )
        if response.get('encoding') != 'base64':
            raise RuntimeError('Unexpected source feed-file encoding')
        feeds = declared_feeds(
            base64.b64decode(response['content']).decode('utf-8'), allowed=template['feeds']
        )
        for required in ('packages', 'luci'):
            if required not in feeds:
                raise RuntimeError(f'Source no longer declares the required {required} feed')
        lock['feeds'] = {}
        # Follow the chosen source tree's branches, not an unrelated newest LuCI branch.
        # Unrelated proxy/telephony additions do not become selected firmware packages.
        for name in template['feeds']:
            if name not in feeds:
                continue
            item = feeds[name]
            if item['commit']:
                lock['feeds'][name] = {key: value for key, value in item.items() if value is not None}
            else:
                lock['feeds'][name] = resolve_ref(item['repository'], item['branch'])
        lock['openclash'] = resolve_ref(
            template['openclash']['repository'], template['openclash'].get('branch', 'master')
        )
        lock['mihomo'] = latest_mihomo()
    elif mode != 'locked':
        raise ValueError('Unknown source resolution mode')
    lock['_resolution'] = {
        'mode': mode,
        'source': source_repository if mode == 'latest' else 'locked',
        'resolved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return lock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['latest', 'locked'], default='latest')
    parser.add_argument('--source-repository', choices=['upstream', 'fork'], default='upstream')
    parser.add_argument('--template', type=Path, default=HERE / 'sources.lock.json')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    template = json.loads(args.template.read_text(encoding='utf-8'))
    lock = resolve_lock(template, args.mode, args.source_repository)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
            handle.write('repository=' + github_repository(lock['lede']['repository']) + '\n')
            handle.write('revision=' + lock['lede']['commit'] + '\n')
    print(f'Recorded exact build inputs in {args.output}', flush=True)


if __name__ == '__main__':
    main()
