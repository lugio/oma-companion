"""Régressions de la préparation à la publication, sans configuration personnelle."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import exemples  # noqa: E402,F401 - avant le moindre module du plugin
import texts
import ha
import dolibarr
import reachy
import backend


class PublicationTests(unittest.TestCase):
    def test_catalogues_identiques(self):
        fr, en = [json.loads((ROOT / 'lang' / f'{l}.json').read_text()) for l in ('fr', 'en')]
        for partie in ('engine', 'panel'):
            self.assertEqual(set(fr[partie]), set(en[partie]))

    def test_phrase_selon_langue_et_personnalisation(self):
        self.assertEqual(backend.DEFAULTS['wakePhrase'], '')
        self.assertEqual(texts.wake_phrase(backend.DEFAULTS | {'language': 'en'}), 'hey alison')
        self.assertEqual(texts.wake_phrase({'language': 'fr', 'wakePhrase': ''}), 'salut alison')
        self.assertEqual(texts.wake_phrase({'language': 'en', 'wakePhrase': 'hello friend'}), 'hello friend')

    def test_erreurs_utilitaires_en_anglais(self):
        with patch.dict(os.environ, COMPANION_LANGUAGE='en'):
            with patch.object(ha, 'CONFIG', ROOT / 'absent.json'):
                output = io.StringIO()
                with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
                    ha.load()
                self.assertIn('not configured', output.getvalue())
            with patch.object(dolibarr, 'credentials', return_value={}):
                output = io.StringIO()
                with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
                    dolibarr.api('/status')
                self.assertIn('not configured', output.getvalue())

    @unittest.skipUnless(shutil.which('node'), 'Node.js requis pour les fonctions QML')
    def test_reglages_hors_barre_conservent_les_cles_inconnues(self):
        source = (ROOT / 'Companion.qml').read_text()
        fonction = source[source.index('    function currentEntry()'):source.index('    // Le shell expose la barre')]
        programme = """
const assert = require('node:assert/strict');
const pluginId = 'companion';
let shell = {barConfig: {layout: {right: [{id: 'other'}]}}};
let savedPluginEntries = [{id: pluginId, language: 'en', custom: 42}];
""" + fonction + """
assert.deepEqual(currentEntry(), savedPluginEntries[0]);
shell.barConfig.layout.left = [{id: pluginId, language: 'fr', extra: 'kept'}];
assert.equal(currentEntry().extra, 'kept');
shell = null;
assert.equal(currentEntry().custom, 42);
savedPluginEntries = [];
assert.deepEqual(currentEntry(), {});
"""
        subprocess.run([shutil.which('node'), '-e', programme], check=True, capture_output=True)

    def test_robot_tester_en_anglais_sans_connexion(self):
        with patch.dict(os.environ, COMPANION_LANGUAGE='en'), patch.object(reachy, 'load_url', return_value=''):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(reachy.cmd_tester(), 1)
            self.assertIn('No robot address', output.getvalue())

    def test_etat_robot_sans_runtime_ne_va_pas_dans_tmp(self):
        env = dict(os.environ, XDG_STATE_HOME='/isolated-state')
        env.pop('XDG_RUNTIME_DIR', None)
        result = subprocess.run([sys.executable, '-c', 'import reachy; print(reachy.PROPRIO_LOG)'],
                                cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), '/isolated-state/reachy-proprio.jsonl')

    def test_refus_image_affiche_dans_la_langue_du_moteur(self):
        agent = backend.Companion.__new__(backend.Companion)
        agent.t = lambda key, **values: texts.t('en', key, **values)
        agent.journal = lambda *args: None
        events = []
        agent.emit = lambda event, **values: events.append((event, values))
        agent.fetch_image('http://example.invalid/image.png')
        self.assertEqual(events[-1][1]['error'], 'HTTPS address required')
        with patch.object(backend, 'public_host', return_value=False):
            agent.fetch_image('https://example.invalid/image.png')
        self.assertEqual(events[-1][1]['error'], 'Local network address refused')

    def test_erreurs_images_traduites(self):
        for i in range(6):
            self.assertNotEqual(texts.t('en', f'err.image.{i}'), texts.t('fr', f'err.image.{i}'))


if __name__ == '__main__':
    unittest.main()
