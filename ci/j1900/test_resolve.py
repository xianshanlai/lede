import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare
import resolve


class SourceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((resolve.HERE / 'sources.lock.json').read_text(encoding='utf-8'))

    @staticmethod
    def release(digest='sha256:' + '1' * 64):
        version = 'v1.20.0'
        name = f'mihomo-linux-amd64-v1-{version}.gz'
        return {
            'tag_name': version, 'draft': False, 'prerelease': False,
            'assets': [
                {'name': f'mihomo-linux-amd64-v3-{version}.gz'},
                {'name': name, 'digest': digest, 'browser_download_url':
                 f'https://github.com/MetaCubeX/mihomo/releases/download/{version}/{name}'},
            ],
        }

    def test_locked_mode_is_offline_and_does_not_mutate_template(self):
        before = json.dumps(self.template, sort_keys=True)
        with patch.object(resolve, 'resolve_ref', side_effect=AssertionError('network called')), \
                patch.object(resolve, 'github_api', side_effect=AssertionError('network called')):
            lock = resolve.resolve_lock(self.template, 'locked', 'upstream')
        self.assertEqual(lock['lede'], self.template['lede'])
        self.assertEqual(lock['feeds'], self.template['feeds'])
        self.assertEqual(lock['_resolution']['mode'], 'locked')
        self.assertEqual(before, json.dumps(self.template, sort_keys=True))

    def test_latest_follows_source_luci_branch_and_honors_pinned_feed(self):
        contents = '\n'.join([
            '#src-git luci https://github.com/coolsnowwolf/luci.git;wrong-branch',
            'src-git packages https://github.com/coolsnowwolf/packages.git',
            'src-git luci https://github.com/coolsnowwolf/luci.git;openwrt-24.10',
            'src-git routing https://github.com/coolsnowwolf/routing.git;main',
            'src-git telephony https://github.com/coolsnowwolf/telephony.git^' + 'e' * 40,
            'src-git unrelated https://git.example.invalid/unrelated.git',
        ])

        def fake_api(endpoint):
            if '/contents/feeds.conf.default?ref=' in endpoint:
                self.assertTrue(endpoint.startswith('repos/coolsnowwolf/lede/'))
                return {'encoding': 'base64', 'content': base64.b64encode(contents.encode()).decode()}
            self.assertEqual(endpoint, 'repos/MetaCubeX/mihomo/releases/latest')
            return self.release()

        def fake_ref(repository, branch=None):
            branches = {'packages.git': 'master', 'routing.git': 'main'}
            return {
                'repository': repository, 'commit': 'a' * 40,
                'branch': branch or branches[repository.rsplit('/', 1)[1]],
            }

        with patch.object(resolve, 'github_api', side_effect=fake_api), \
                patch.object(resolve, 'resolve_ref', side_effect=fake_ref) as refs:
            lock = resolve.resolve_lock(self.template, 'latest', 'upstream')
        self.assertEqual(lock['lede']['repository'], self.template['lede']['upstream_repository'])
        self.assertEqual(lock['feeds']['luci']['branch'], 'openwrt-24.10')
        self.assertEqual(lock['feeds']['telephony']['commit'], 'e' * 40)
        self.assertNotIn('unrelated', lock['feeds'])
        self.assertFalse(any('telephony.git' in call.args[0] for call in refs.call_args_list))
        self.assertEqual(lock['mihomo']['version'], 'v1.20.0')
        self.assertIn('amd64-v1-', lock['mihomo']['url'])

    def test_fork_mode_resolves_the_users_repository(self):
        # A saved upstream run can still retain the user's fork for future builds.
        self.template['lede']['repository'] = self.template['lede']['upstream_repository']
        with patch.object(resolve, 'resolve_ref', side_effect=RuntimeError('stop')) as ref:
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                resolve.resolve_lock(self.template, 'latest', 'fork')
        ref.assert_called_once_with(self.template['lede']['fork_repository'], 'master')

    def test_mihomo_without_checksum_is_rejected(self):
        with patch.object(resolve, 'github_api', return_value=self.release(digest=None)):
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                resolve.latest_mihomo()

    def test_unavailable_compatible_core_is_rejected(self):
        release = self.release()
        release['assets'] = release['assets'][:1]
        with patch.object(resolve, 'github_api', return_value=release):
            with self.assertRaisesRegex(RuntimeError, 'amd64-v1'):
                resolve.latest_mihomo()

    def test_git_default_branch_is_recorded(self):
        output = 'ref: refs/heads/main\tHEAD\n' + 'b' * 40 + '\tHEAD\n'
        with patch.object(resolve.subprocess, 'check_output', return_value=output):
            ref = resolve.resolve_ref('https://github.com/example/feed.git')
        self.assertEqual(ref['branch'], 'main')
        self.assertEqual(ref['commit'], 'b' * 40)

    def test_prepare_accepts_a_run_specific_resolved_lock(self):
        lock = json.loads(json.dumps(self.template))
        lock['lede']['commit'] = 'a' * 40
        with tempfile.TemporaryDirectory(prefix='.test-resolve-', dir=resolve.HERE) as directory:
            path = Path(directory) / 'sources.resolved.json'
            path.write_text(json.dumps(lock), encoding='utf-8')
            selected, _ = prepare.check_inputs(path)
        self.assertEqual(selected['lede']['commit'], 'a' * 40)


if __name__ == '__main__':
    unittest.main()
