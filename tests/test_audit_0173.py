"""Relecture du store #12144 : la connexion IMAP doit vérifier le serveur avant d'envoyer le mot de passe."""
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import exemples  # noqa: E402,F401 - avant le moindre module du plugin
import mail


class MailTlsTests(unittest.TestCase):
    def test_contexte_verifiant_transmis(self):
        seen = {}

        def fake(host, port, ssl_context=None, timeout=None):
            seen["context"] = ssl_context
            raise OSError("stop")

        account = {"email": "a" + "@example.org", "password": "faux-secret", "imap_host": "imap.example.org"}
        with patch.object(mail, "credentials", return_value=account), patch.object(mail.imaplib, "IMAP4_SSL", fake):
            with self.assertRaises(RuntimeError):
                mail.connect()
        self.assertIsNotNone(seen["context"])
        self.assertEqual(seen["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(seen["context"].check_hostname)

    def test_faux_serveur_ne_recoit_pas_le_mot_de_passe(self):
        with tempfile.TemporaryDirectory() as folder:
            cert, key = Path(folder) / "c.pem", Path(folder) / "k.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)],
                           check=True, capture_output=True)
            server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ctx.load_cert_chain(cert, key)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            received = []

            def serve():
                conn, _ = listener.accept()
                try:
                    with server_ctx.wrap_socket(conn, server_side=True) as tls:
                        tls.sendall(b"* OK IMAP4rev1 faux serveur\r\n")
                        tls.settimeout(3)
                        while chunk := tls.recv(4096):
                            received.append(chunk)
                except (ssl.SSLError, OSError):
                    pass

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            account = {"email": "a" + "@example.org", "password": "faux-secret-imap",
                       "imap_host": "localhost", "imap_port": listener.getsockname()[1]}
            with patch.object(mail, "credentials", return_value=account), \
                 patch.dict(os.environ, {"COMPANION_LANGUAGE": "en"}):
                with self.assertRaises(RuntimeError) as caught:
                    mail.connect()
            thread.join(5)
            listener.close()
        self.assertIn("not trusted", str(caught.exception))
        self.assertNotIn(b"faux-secret-imap", b"".join(received))


if __name__ == "__main__":
    unittest.main()
