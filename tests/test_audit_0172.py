"""Scénarios adverses de l’audit 0.17.2, sans accès aux services réels."""
import contextlib
import io
import glob
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import guard
import agents
import roles
import sauvegarde
import delegue
import apercu


class Audit0172Tests(unittest.TestCase):
    def hook(self, command, mode='code', extra=()):
        with tempfile.TemporaryDirectory() as folder:
            return subprocess.run([sys.executable, str(ROOT / 'guard.py'), mode, *extra],
                                  input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}}),
                                  text=True, capture_output=True,
                                  env=dict(os.environ, XDG_STATE_HOME=folder))

    def test_A1_lecture_refuse_options_ecriture_et_execution(self):
        for prefix in agents.READ_ONLY_PREFIXES:
            self.assertIn(prefix.split()[0], guard.READ_OPTIONS, prefix)
        for command in ('file -C -m ./example.magic', 'date --set=tomorrow', 'ls --format=long --unknown',
                        'journalctl --rotate', 'pgrep --unknown=x', 'upower --wakeup',
                        'file -z archive.gz', 'file *', "file $'-C' -m example.magic",
                        'date --date=$(touch output)', 'cat input > output', 'fastfetch', 'LD_PRELOAD=./attack.so cat document', 'systemctl status --root=./fake'):
            with self.subTest(command=command):
                result = self.hook(command, 'read')
                self.assertEqual(result.returncode, 2, (command, result.stdout, result.stderr))
                self.assertNotIn('"ask"', result.stdout)
        self.assertEqual(self.hook('file -b document', 'read').returncode, 0)

    def test_enchainements_controles_un_a_un_restent_utilisables(self):
        # Relecture du 19/10 : `|`, `;`, `&&` ne rendent pas une commande suspecte — chaque morceau est contrôlé.
        for command in ("cat document | grep mot", "ls; date", "cat a && cat b", "cat a || cat b"):
            with self.subTest(command=command):
                self.assertEqual(guard.needs_card("Bash", {"command": command}, "read"), "")
        # … mais un morceau dangereux reste refusé, et une redirection l'est toujours.
        for command in ("cat document | file -C -m x.magic", "cat a > b", "ls; cat $(touch x)"):
            with self.subTest(command=command):
                self.assertNotEqual(guard.needs_card("Bash", {"command": command}, "read"), "")

    def test_A2_awk_alias_et_argument_uniq_ne_disparaissent_plus(self):
        for command in ('awk -W file=./attack.awk', 'awk -Wfile=./attack.awk',
                        'uniq input result=output', 'LC_ALL=C uniq input result=output',
                        'diff --output=output input other', 'git diff --no-index --output=output a b',
                        'sort --out=output input', 'rg --hostname-bin=./attack pattern',
                        'find . -fprint output', "jq 'include \"attack\"; .' data"):
            with self.subTest(command=command):
                result = self.hook(command)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'], 'ask')
        self.assertEqual(guard.needs_card('Bash', {'command': 'uniq input'}, 'code'), '')

    def test_A3_expansions_helpers_refusees_avant_le_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'cover.gate').touch()
            self.assertEqual(glob.glob('cove?.gate', root_dir=folder), ['cover.gate'])
        for arg in ('cove?.gate', 'cove*.gate', 'cove[r].gate', '{light,cover}.gate', '~',
                    '$ENTITY', '`cat entity`', '$(cat entity)', 'cover\\.gate', 'cover.gate > out'):
            with self.subTest(arg=arg):
                command = 'python3 /plugin/ha.py off ' + arg
                self.assertIsNotNone(guard.check('Bash', {'command': command}, 'assistant'))
        self.assertIsNone(guard.check('Bash', {'command': 'python3 /plugin/ha.py off light.example'}, 'assistant'))

    def test_A4_nom_role_non_canonique_ne_remplace_pas_actif(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(roles, 'STANDARD', Path(folder)):
            roles._cache.clear()
            form = {'name': 'restricted', 'persona_text': 'Read only.', 'ceiling': 'read', 'access': []}
            self.assertIsNone(roles.save({}, form))
            before = (Path(folder) / 'restricted/role.json').read_bytes()
            for name in ('restricted\n', ' restricted', 'restricted ', 'RESTRICTED', '../restricted'):
                with self.subTest(name=name):
                    data = {'roles': {name: {'persona': 'Escalate', 'modes': list(agents.MODES)}}}
                    config = {'role': 'restricted'}
                    _, errors = sauvegarde.apply(data, config, {}, lambda _: self.fail('personnalité écrite'))
                    self.assertTrue(errors)
                    self.assertEqual((Path(folder) / 'restricted/role.json').read_bytes(), before)
                    self.assertIsNotNone(roles.save({}, form | {'name': name}, dry_run=True))
            _, errors = sauvegarde.apply({'roles': {'restricted': {'persona': 'Escalate', 'modes': list(agents.MODES)}}},
                                           {'role': 'restricted'}, {}, lambda _: None, replace_roles=True)
            self.assertTrue(errors)
            self.assertEqual((Path(folder) / 'restricted/role.json').read_bytes(), before)
            outside = Path(folder) / 'outside.txt'
            outside.write_text('Private fixture')
            data = {'roles': {'fresh': {'modes': ['chat'], 'persona': 'Safe imported personality',
                                      'name': '../restricted', 'persona_path': str(outside),
                                      'files': {'../outside.txt': 'overwrite'}}}}
            _, errors = sauvegarde.apply(data, {}, {}, lambda _: self.fail('personnalité écrite'))
            self.assertEqual(errors, [])
            self.assertEqual(outside.read_text(), 'Private fixture')
            self.assertEqual((Path(folder) / 'fresh/role.md').read_text().strip(), 'Safe imported personality')
            roles._cache.clear()

    def test_A5_catalogue_lanceurs_refuse_lua_et_exec(self):
        for command in ('''hyprctl dispatch 'hl.dsp.exec_cmd("python3 -c pass")' ''',
                        'hyprctl dispatch exec_cmd /usr/bin/python3',
                        '''hyprctl -j dispatch 'hl.dsp.exec_cmd("python3 -c pass")' ''',
                        'hyprctl --batch dispatch-exec', 'hyprctl dispatch exec firefox',
                        'uwsm app -- /usr/bin/printf data', 'omarchy launch anything shell',
                        'xdg-open ./malicious.desktop', 'systemctl --user set-environment PATH=./attack',
                        'systemctl --user link /tmp/attack.service',
                        '''env hyprctl dispatch 'hl.dsp.exec_cmd("python3 -c pass")' ''',
                        'omarchy version; python3 -c pass'):
            with self.subTest(command=command):
                self.assertIsNotNone(guard.check('Bash', {'command': command}, 'code'))
        for command in ('hyprctl dispatch workspace 4', 'uwsm app -t service -- firefox.desktop',
                        'omarchy launch browser https://example.invalid/', 'systemctl --user restart example.service'):
            with self.subTest(command=command):
                self.assertIsNone(guard.check('Bash', {'command': command}, 'code'))

    def test_A6_chemins_prives_et_question_absents_argv(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(agents, 'RUN_DIR', Path(folder) / 'private'):
            hook = agents.guard_hook('assistant', ['/private/fictional-location'], ['blocked'])
            argv = shlex.split(hook['PreToolUse'][0]['hooks'][0]['command'])
            self.assertNotIn('/private/fictional-location', ' '.join(argv))
            policy = Path(argv[argv.index('--policy-file') + 1])
            self.assertEqual(policy.stat().st_mode & 0o777, 0o600)
            self.assertEqual(policy.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(policy.read_text())['private'], ['/private/fictional-location'])
            result = self.hook('cat /private/fictional-location', extra=('--policy-file', str(policy)))
            self.assertEqual(result.returncode, 2)
            policy.chmod(0o644)
            self.assertEqual(self.hook('cat normal-file', extra=('--policy-file', str(policy))).returncode, 2)
            policy.unlink()
            session = agents.ClaudeSession('Example prompt', '', private=['/private/fictional-location'])
            with patch.object(agents, 'workdir', return_value=folder), \
                 patch.object(agents.subprocess, 'Popen', side_effect=OSError('test launch failure')):
                with self.assertRaises(OSError):
                    session.start(False)
            self.assertEqual(session.files, [])
            self.assertEqual(list((Path(folder) / 'private').iterdir()), [])
        with tempfile.TemporaryDirectory() as folder, patch.object(agents, 'RUN_DIR', Path(folder) / 'private'):
            hook = agents.guard_hook('read', delegate=True)
            words = shlex.split(hook['PreToolUse'][0]['hooks'][0]['command'])
            policy = Path(words[words.index('--policy-file') + 1])
            question = 'Confidential fictional business question.'
            command = shlex.join(['python3', str(ROOT / 'delegue.py'), 'example', question])
            result = self.hook(command, 'read', ('--policy-file', str(policy)))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)['hookSpecificOutput']
            self.assertNotIn('permissionDecision', output)
            updated = output['updatedInput']['command']
            self.assertNotIn(question, updated)
            self.assertNotIn(question, result.stdout)
            argv = shlex.split(updated)
            request = Path(argv[-1])
            self.assertEqual(request.stat().st_mode & 0o777, 0o600)
            self.assertEqual(delegue.read_question(argv[2:], io.StringIO('')), question)
            self.assertFalse(request.exists())
            self.assertEqual(self.hook(command, 'read').returncode, 2)
            self.assertEqual(self.hook('python3 ' + str(ROOT / 'delegue.py') + " example <<'EOF'\n" + question + '\nEOF',
                                       'read', ('--policy-file', str(policy))).returncode, 2)
        self.assertEqual(delegue.read_question(['role'], io.StringIO('Business question.')), 'Business question.')
        with self.assertRaises(ValueError):
            delegue.read_question(['role', 'Business question.'], io.StringIO(''))

    def test_A7_carte_montre_modification_malveillante_en_fin(self):
        marker = 'ATTACK_AT_END'
        content = 'safe\n' * 500 + marker
        for request in (
            {'tool_name': 'Write', 'input': {'file_path': '/project/file', 'content': content}},
            {'tool_name': 'Edit', 'input': {'file_path': '/project/file', 'old_string': content, 'new_string': content}},
            {'tool_name': 'MultiEdit', 'input': {'file_path': '/project/file', 'edits': [
                {'old_string': 'x', 'new_string': 'y'}, {'old_string': 'safe', 'new_string': content}]}}):
            with self.subTest(tool=request['tool_name']):
                self.assertIn(marker, agents.describe_request(request))

    def test_A8_texte_libre_excluable_et_inspectable(self):
        marker = 'fictional confidential business text'
        role = {'name': 'example', 'label': 'Example', 'persona': marker, 'description': marker, 'modes': ['chat']}
        with patch.object(roles, 'available', return_value=[{'name': 'example'}]), \
             patch.object(roles, 'load', return_value=role), patch.object(roles, 'editable', return_value=True), \
             patch.object(sauvegarde.maison, 'load', return_value=[]):
            data = sauvegarde.export({}, marker, include_persona=False, include_roles=False)
            self.assertNotIn(marker, json.dumps(data))
            self.assertNotIn('persona', data)
            self.assertEqual(data['roles'], {})
            data = sauvegarde.export({}, marker)
            preview = sauvegarde.preview(data, {}, {})
            self.assertEqual(preview['personaText'], marker)
            self.assertEqual(preview['roleContents']['example']['persona'], marker)

    def test_A9_ancien_cookie_ne_survit_pas_a_une_reouverture(self):
        with tempfile.TemporaryDirectory() as folder:
            processes = []
            class Process:
                pid = 12345
                def poll(self): return None
                def terminate(self): pass
                def wait(self, timeout=None): return 0
            def launch(argv, **kwargs):
                processes.append(argv)
                return Process()
            with patch.object(apercu, 'PROFILE', Path(folder) / 'profile'), \
                 patch.object(apercu, 'PID_FILE', Path(folder) / 'preview.pid'), \
                 patch.object(apercu, 'default_browser', return_value='firefox.desktop'), \
                 patch.object(apercu.subprocess, 'Popen', side_effect=launch), \
                 patch.object(apercu, 'watch_cleanup'), patch.object(apercu.os, 'kill'), \
                 patch.object(apercu, 'wait_exit', return_value=True):
                apercu.open_window('https://example.invalid/')
                first = Path(processes[-1][processes[-1].index('--profile') + 1])
                (first / 'cookies.sqlite').write_text('old authentication')
                apercu.open_window('https://example.invalid/')
                second = Path(processes[-1][processes[-1].index('--profile') + 1])
                self.assertNotEqual(first, second)
                self.assertFalse(first.exists())
                self.assertFalse((second / 'cookies.sqlite').exists())
                apercu.close()
                self.assertFalse(second.exists())

    def test_A9_nettoyage_apres_sortie_naturelle_du_processus(self):
        with tempfile.TemporaryDirectory() as folder:
            # Le veilleur reçoit la même racine par environnement que le processus appelant.
            env = dict(os.environ, XDG_STATE_HOME=folder)
            script = """
import apercu, subprocess, sys, tempfile, time
from pathlib import Path
apercu.PROFILE.parent.mkdir(parents=True)
profile = Path(tempfile.mkdtemp(prefix=apercu.PROFILE.name + '-', dir=apercu.PROFILE.parent))
(profile / 'cookies.sqlite').write_text('fictional previous session')
process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.1)'])
apercu.watch_cleanup(process, profile)
process.wait()
for _ in range(100):
    if not profile.exists(): break
    time.sleep(.02)
assert not profile.exists(), 'profile survived browser exit'
"""
            result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_A10_doc_systemctl_et_certification_sans_promesse_fausse(self):
        doc = (ROOT / 'docs/maintainers.md').read_text()
        self.assertNotIn('**refused command**', doc)
        for word in ('list-unit-files', 'is-active', '--user', 'approval', '2.1.*'):
            self.assertIn(word, doc)


if __name__ == '__main__':
    unittest.main()
