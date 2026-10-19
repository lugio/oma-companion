"""Whisper ne télécharge qu'au clic et ne charge que les octets épinglés."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import download_models as downloads
import stt


class WhisperVerifiedTests(unittest.TestCase):
    def test_missing_files_never_reach_the_loader_or_network(self):
        for lang, instruction in (("fr", "Installer la voix"), ("en", "Install the voice")):
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as root, \
                 patch.object(stt, "WHISPER", Path(root), create=True), patch.object(stt, "LANG", lang), \
                 patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=Mock())}), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("réseau interdit")) as network:
                with self.assertRaisesRegex(FileNotFoundError, instruction):
                    stt.load_whisper()
                sys.modules["faster_whisper"].WhisperModel.assert_not_called()
                network.assert_not_called()

    def test_the_commit_inventory_is_complete(self):
        expected = {".gitattributes", "README.md", "config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}
        self.assertEqual(set(getattr(downloads, "WHISPER_FILES", {})), expected)
        for name, digest in downloads.WHISPER_FILES.items():
            url, declared = downloads.MODELS["faster-whisper-small/" + name]
            self.assertIn("/536b0662742c02347bc0e980a01041f333bce120/", url)
            self.assertEqual(declared, digest)
            self.assertRegex(digest, r"^[a-f0-9]{64}$")

    def test_a_bad_download_is_never_activated(self):
        with tempfile.TemporaryDirectory() as root, patch.object(downloads, "DEST", Path(root)), \
             patch("urllib.request.urlopen", return_value=io.BytesIO(b"corrompu")):
            name = "faster-whisper-small/model.bin"
            with self.assertRaises(ValueError):
                downloads.download((name, ("https://example.org/model.bin", hashlib.sha256(b"attendu").hexdigest())))
            self.assertFalse((Path(root) / name).exists())
            self.assertFalse((Path(root) / (name + ".part")).exists())

    def test_checked_local_files_only_and_tampering_rejected(self):
        inventory = {name: hashlib.sha256(name.encode()).hexdigest()
                     for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")}
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            for name in inventory:
                (folder / name).write_bytes(name.encode())
            factory = Mock()
            with patch.object(stt, "WHISPER", folder, create=True), \
                 patch.object(downloads, "WHISPER_FILES", inventory, create=True), \
                 patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=factory)}), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("réseau interdit")):
                stt.load_whisper()
                args, kwargs = factory.call_args
                self.assertEqual(args, (str(folder),))
                self.assertTrue(kwargs["local_files_only"])
                self.assertNotIn("download_root", kwargs)
                (folder / "tokenizer.json").write_text("altéré")
                factory.reset_mock()
                with self.assertRaises(ValueError):
                    stt.load_whisper()
                factory.assert_not_called()

    def test_missing_whisper_falls_back_to_parakeet(self):
        with tempfile.TemporaryDirectory() as root, patch.object(stt, "ENGINE", "whisper"), \
             patch.object(stt, "WHISPER", Path(root), create=True), \
             patch.object(stt, "load_parakeet", return_value=lambda path: ("texte", {})):
            transcribe, label = stt.load()
            self.assertEqual(label, "parakeet-v3 (repli)")
            self.assertEqual(transcribe("test.wav")[0], "texte")

    def test_model_name_override_cannot_select_another_remote_model(self):
        # Le module doit ignorer cette ancienne surcharge, même à son import.
        import importlib.util
        spec = importlib.util.spec_from_file_location("stt_essai", Path(stt.__file__))
        module = importlib.util.module_from_spec(spec)
        with patch.dict("os.environ", {"COMPANION_STT_MODEL": "organisation/modele-non-epingle"}):
            spec.loader.exec_module(module)
        self.assertEqual(module.MODEL, "small")

    def test_a_present_but_altered_model_can_be_repaired_on_click(self):
        # L'action de réparation doit rester accessible même si le dossier paraît complet.
        view = (Path(stt.__file__).parent / "SettingsView.qml").read_text()
        self.assertTrue("visible: settings.app.voiceReady && settings.app.voiceComplete" in view)
        self.assertTrue("text: settings.app.tr.voice_verify" in view)
        content = b"modele verifie"
        with tempfile.TemporaryDirectory() as root, patch.object(downloads, "DEST", Path(root)), \
             patch("urllib.request.urlopen", return_value=io.BytesIO(content)):
            path = Path(root) / "faster-whisper-small/model.bin"
            path.parent.mkdir()
            path.write_bytes(b"altere")
            downloads.download(("faster-whisper-small/model.bin",
                                ("https://example.org/model.bin", hashlib.sha256(content).hexdigest())))
            self.assertEqual(path.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
