"""Télécharge les modèles de voix vérifiés par empreinte SHA-256.

Les adresses utilisent une révision fixe quand l'hôte le permet. Quel que soit l'hôte,
un fichier dont l'empreinte diffère est rejeté, jamais installé.
"""
import concurrent.futures
import hashlib
import os
from pathlib import Path
import tarfile
import urllib.request
import zipfile

DEST = Path(os.environ.get("COMPANION_DATA_HOME", str(Path.home() / ".local/share/omarchy-companion"))) / "models"
WHISPER_CPP = "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1"
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/1162a9173d0ce503555aed757976b7a9912eae4c"
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
WHISPER_URL = f"https://huggingface.co/Systran/faster-whisper-small/resolve/{WHISPER_REVISION}"
# Inventaire COMPLET du commit : quatre fichiers d'inférence et deux notices/métadonnées.
# model.bin : SHA-256 publié dans le pointeur LFS ; autres fichiers : octets téléchargés et
# hachés le 19/10/2026 à cette révision, sans passer par une représentation HTML.
WHISPER_FILES = {
    ".gitattributes": "db7c0371f46f0840b8f25794c1e3321c9b5820a8cb6ba9694a46fc64b8fae5a6",
    "README.md": "329373481008c7c38654aff8ecdcf0163c211557cc7ba8e2ef6f2f84b4f75ec8",
    "config.json": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
    "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
}
MODELS = {
    "ggml-base.bin": (f"{WHISPER_CPP}/ggml-base.bin",
                      "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"),
    "fr_FR-siwis-medium.onnx": (f"{PIPER}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
                                "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99"),
    "fr_FR-siwis-medium.onnx.json": (f"{PIPER}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json",
                                     "39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959"),
    "vosk-fr.zip": ("https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip",
                    "cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad"),
    # Anglais (réglage « language ») : voix Piper Lessac, mot d'éveil Vosk small en-us.
    "en_US-lessac-medium.onnx": (f"{PIPER}/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
                                 "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"),
    "en_US-lessac-medium.onnx.json": (f"{PIPER}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
                                      "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"),
    "vosk-en.zip": ("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
                    "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"),
}
MODELS.update({f"faster-whisper-small/{name}": (f"{WHISPER_URL}/{name}", digest)
               for name, digest in WHISPER_FILES.items()})
TIMEOUT = 60


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(item):
    name, (url, expected) = item
    path = DEST / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha256(path) == expected:
        print(name, "déjà présent, empreinte vérifiée", flush=True)
        return
    part = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response, open(part, "wb") as handle:
            for block in iter(lambda: response.read(1 << 20), b""):
                handle.write(block)
        actual = sha256(part)
        if actual != expected:
            raise ValueError(f"{name} : empreinte inattendue ({actual}), fichier rejeté")
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
    print(name, path.stat().st_size, "octets, empreinte vérifiée", flush=True)


# Parakeet TDT 0.6B v3 int8 (sherpa-onnx), moteur de transcription par défaut depuis le 09/10/2026.
# Archive de la publication officielle (adresse fixe), puis CHAQUE fichier extrait vérifié : l'archive
# n'est pas gardée (465 Mo), seuls les quatre fichiers utiles le sont, dans models/parakeet-v3/.
PARAKEET_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2")
PARAKEET_ARCHIVE = "5793d0fd397c5778d2cf2126994d58e9d56b1be7c04d13c7a15bb1b4eafb16bf"
PARAKEET_FILES = {
    "encoder.int8.onnx": "acfc2b4456377e15d04f0243af540b7fe7c992f8d898d751cf134c3a55fd2247",
    "decoder.int8.onnx": "179e50c43d1a9de79c8a24149a2f9bac6eb5981823f2a2ed88d655b24248db4e",
    "joiner.int8.onnx": "3164c13fc2821009440d20fcb5fdc78bff28b4db2f8d0f0b329101719c0948b3",
    "tokens.txt": "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
}


def parakeet():
    folder = DEST / "parakeet-v3"
    if all((folder / name).exists() and sha256(folder / name) == digest for name, digest in PARAKEET_FILES.items()):
        print("parakeet-v3 déjà présent, empreintes vérifiées", flush=True)
        return
    folder.mkdir(parents=True, exist_ok=True)
    part = DEST / "parakeet-v3.tar.bz2.part"
    try:
        with urllib.request.urlopen(PARAKEET_URL, timeout=TIMEOUT) as response, open(part, "wb") as handle:
            for block in iter(lambda: response.read(1 << 20), b""):
                handle.write(block)
        if sha256(part) != PARAKEET_ARCHIVE:
            raise ValueError("parakeet-v3 : empreinte de l'archive inattendue, rejetée")
        with tarfile.open(part, "r:bz2") as archive:
            for member in archive.getmembers():
                name = Path(member.name).name
                if name not in PARAKEET_FILES or not member.isfile():
                    continue        # seuls les quatre fichiers attendus, jamais un chemin de l'archive
                source = archive.extractfile(member)
                target = folder / (name + ".part")
                with open(target, "wb") as handle:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        handle.write(block)
                if sha256(target) != PARAKEET_FILES[name]:
                    target.unlink()
                    raise ValueError(f"parakeet-v3/{name} : empreinte inattendue, rejeté")
                target.replace(folder / name)
    finally:
        part.unlink(missing_ok=True)
    print("parakeet-v3 installé, empreintes vérifiées", flush=True)


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, MODELS.items()))
    parakeet()
    for zipped in ("vosk-fr.zip", "vosk-en.zip"):
        with zipfile.ZipFile(DEST / zipped) as archive:
            for name in archive.namelist():
                if not (DEST / name).resolve().is_relative_to(DEST.resolve()):
                    raise ValueError("Archive invalide")
            archive.extractall(DEST)
