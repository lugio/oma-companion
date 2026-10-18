#!/usr/bin/env python3
"""Recherche des traces personnelles dans les fichiers SUIVIS du dépôt (installation fraîche, 18/10/2026).

    python3 tests/check_traces.py            # liste fichier:ligne:marqueur, code 1 s'il en reste

Le dépôt est générique : aucune personne, entreprise, machine, adresse ni chemin de l'auteur. La liste des
marqueurs est PRIVÉE — elle nommerait justement ce qu'on cache : un fichier hors du dépôt, désigné par
`COMPANION_TRACES` (une expression régulière par ligne, casse ignorée, « # » pour un commentaire). Sans
liste, le contrôle le dit et ne conclut rien.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = {"tests/check_traces.py", "LICENSE"}
LIST = os.environ.get("COMPANION_TRACES", "")


def main():
    if not LIST or not Path(LIST).expanduser().is_file():
        print("pas de liste de marqueurs (COMPANION_TRACES) : rien à vérifier", file=sys.stderr)
        return 2
    patterns = [line.strip() for line in Path(LIST).expanduser().read_text().splitlines()
                if line.strip() and not line.startswith("#")]
    marker = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    found = 0
    for name in files:
        if name in IGNORE:
            continue
        try:
            text = (ROOT / name).read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in marker.finditer(line):
                print(f"{name}:{number}:{match.group(0)}")
                found += 1
    print(f"{found} trace(s)", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
