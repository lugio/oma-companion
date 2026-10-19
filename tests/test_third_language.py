"""Une traduction seule ne prétend pas fournir une grammaire ou des modèles vocaux."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import exemples  # avant les modules du plugin : uniquement des réglages fictifs
import backend
import stt
import texts

ROOT = Path(__file__).resolve().parents[1]


class ThirdLanguageTests(unittest.TestCase):
    def test_server_starts_with_translated_and_unknown_languages(self):
        program = '''
import io, json, sys
import stt
assert stt.PROMPT == "", "contexte trompeur"
assert stt.TRANSCRIBE_OPTIONS["language"] == sys.argv[1], "langue remplacée"
assert stt.drop_noise("Merci d'avoir regardé.") == "Merci d'avoir regardé."
assert stt.drop_noise("Thank you.") == "Thank you."
stt.load_parakeet = lambda: (lambda path: ("texte", {}))
stt.load_whisper = lambda: (lambda path: ("texte", {}))
sys.stdin = io.StringIO('{"quit": true}\\n')
stt.main()
'''
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / '.config/omarchy-companion/lang'
            folder.mkdir(parents=True)
            for lang in ('de', 'es'):
                (folder / (lang + '.json')).write_text(json.dumps({'name': lang, 'panel': {}, 'engine': {}}))
            for lang in ('de', 'es', 'zz'):
                with self.subTest(lang=lang):
                    result = subprocess.run([sys.executable, '-c', program, lang], cwd=ROOT, capture_output=True,
                                            text=True, env={'HOME': directory, 'PATH': '/usr/bin:/bin',
                                                            'COMPANION_STT_LANG': lang})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['event'], 'ready')

    def test_a_language_outside_parakeet_never_uses_it_even_as_fallback(self):
        for lang in ('zh', 'ja', 'zz'):
            with self.subTest(lang=lang), patch.object(stt, 'LANG', lang), patch.object(stt, 'ENGINE', 'parakeet'), \
                 patch.object(stt, 'load_parakeet') as parakeet, patch.object(stt, 'load_whisper', return_value='whisper'):
                self.assertEqual(stt.load(), ('whisper', 'small'))
                parakeet.assert_not_called()
            with patch.object(stt, 'LANG', lang), patch.object(stt, 'load_parakeet') as parakeet, \
                 patch.object(stt, 'load_whisper', side_effect=RuntimeError('indisponible')):
                with self.assertRaises(RuntimeError):
                    stt.load()
                parakeet.assert_not_called()

    def test_supported_parakeet_languages_keep_the_selected_engine_and_fallback(self):
        for lang in ('fr', 'en', 'de', 'es', 'uk'):
            with self.subTest(lang=lang), patch.object(stt, 'LANG', lang), patch.object(stt, 'ENGINE', 'parakeet'), \
                 patch.object(stt, 'load_parakeet', return_value='parakeet'), patch.object(stt, 'load_whisper') as whisper:
                self.assertEqual(stt.load(), ('parakeet', 'parakeet-v3'))
                whisper.assert_not_called()

    def test_voxtype_has_no_french_context_for_a_third_language(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'models').mkdir()
            (root / 'models/ggml-base.bin').touch()
            with patch.object(backend, 'ROOT', root), patch.object(backend, 'STATE', root / 'state'), \
                 patch.object(backend.Path, 'home', return_value=root):
                import tomllib
                for lang in ('de', 'es', 'zz'):
                    path, _ = backend.voxtype_config(lang)
                    config = tomllib.loads(path.read_text())['whisper']
                    self.assertEqual(config['initial_prompt'], '')
                    self.assertEqual(config['language'], lang)

    def test_voice_import_uses_the_existing_english_fallback(self):
        spec = importlib.util.spec_from_file_location('voice_essai', ROOT / 'voice.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict('os.environ', {'COMPANION_LANG': 'de'}), patch.object(texts, 'LANGUAGES', ('fr', 'en', 'de')):
            spec.loader.exec_module(module)
        self.assertEqual(module.MODEL.name, texts.VOICE['en']['tts'])

    def test_approval_and_stop_words_are_exactly_the_old_english_fallback(self):
        for lang in ('de', 'es', 'zz'):
            self.assertEqual(texts.decision_words(lang), texts.decision_words('en'))
            self.assertEqual(texts.barge_words(lang), texts.barge_words('en'))
            self.assertEqual(texts.decision_words(lang)[0], ['approve', 'go ahead', 'allow it'])
            for word in ('ja', 'sí', 'si', 'oui', 'yes'):
                self.assertNotIn(word, texts.decision_words(lang)[0])

    def test_fallback_is_reported_once_and_exposed_to_the_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, 'STATE', Path(directory)):
            agent = backend.Companion()
            self.addCleanup(agent.pool.shutdown)
            agent.journal = Mock()
            notice = agent.voice_language_notice('de')
            self.assertIn('English', notice)
            self.assertIn('de', notice)
            self.assertEqual(agent.voice_language_notice('de'), notice)
            self.assertEqual(agent.journal.call_count, 1)
            self.assertEqual(agent.voice_language_notice('fr'), '')
            self.assertEqual(agent.voice_language_notice('en'), '')
            self.assertEqual(agent.journal.call_count, 1)
        engine = (ROOT / 'backend.py').read_text()
        self.assertGreaterEqual(engine.count('voiceLanguageNotice=self.voice_language_notice(lang)'), 2)
        view = (ROOT / 'SettingsView.qml').read_text()
        self.assertTrue('text: settings.app.voiceLanguageNotice' in view)
        panel = (ROOT / 'Companion.qml').read_text()
        self.assertGreaterEqual(panel.count('voiceLanguageNotice = data.voiceLanguageNotice || ""'), 2)

    @unittest.skipUnless(shutil.which('node'), 'Node.js requis pour les fonctions du panneau')
    def test_switching_to_a_translation_replaces_the_old_default_wake_phrase(self):
        panel = (ROOT / 'Companion.qml').read_text()
        wake = panel[panel.index('    function wakeOf(code)'):panel.index('    function t(key,')]
        setting = panel[panel.index('    function setSetting(key, value)'):panel.index('    // Une pastille')]
        program = '''
const assert = require('node:assert/strict');
let languages = [{code:'fr',wake:'salut alison'}, {code:'en',wake:'hey alison'}, {code:'de',wake:''}];
let root = {lang:'fr'}, wakePhrase = '', service = null;
function saveSettings() {}
''' + wake + setting + '''
setSetting('language', 'en');
assert.equal(wakePhrase, 'hey alison');
setSetting('language', 'fr');
assert.equal(wakePhrase, 'salut alison');
setSetting('language', 'de');
assert.equal(wakePhrase, 'hey alison');
wakePhrase = 'my custom phrase';
setSetting('language', 'fr');
setSetting('language', 'de');
assert.equal(wakePhrase, 'my custom phrase');
'''
        result = subprocess.run([shutil.which('node')], input=program, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
