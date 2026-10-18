"""Outil de développement : retire Alison par Omarchy. Historique, réglages de voix et modèles
restent dans ~/.local/state et ~/.local/share/omarchy-companion ; la ligne de raccourci éventuelle
dans ~/.config/hypr/bindings.lua est à retirer soi-même."""
import json
from pathlib import Path
import subprocess

PLUGIN_ID = json.loads((Path(__file__).resolve().parent / "manifest.json").read_text())["id"]

subprocess.run(["omarchy", "plugin", "remove", PLUGIN_ID, "--yes"], check=True)
print(f"Alison retirée ({PLUGIN_ID}). Données conservées dans ~/.local/state et ~/.local/share/omarchy-companion.")
