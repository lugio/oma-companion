#!/usr/bin/env python3
"""QA du protocole panneau, sans cerveau, réseau ni configuration personnelle.

Lancer : python3 tests/qa_parcours.py. Aucun module du moteur n'est importé
par le pilote. Les fichiers temporaires restent dans le dépôt puis sont détruits.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
MODES = ['chat', 'read', 'assistant', 'code', 'auto']
# Chargé avant backend.py : aucune modification du moteur, garde au niveau Python.
GUARD = r'''
import os, sys
from pathlib import Path
home = Path(os.environ['HOME']).resolve()
repo = Path(os.environ['QA_REPO']).resolve()
real_home = Path(os.environ['QA_REAL_HOME']).resolve()   # le vrai dossier personnel : jamais lu
def inside(p, root):
    return p == root or root in p.parents
def audit(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork'):
        raise PermissionError('QA: réseau/processus externe interdit')
    paths = []
    if event == 'open' and not isinstance(args[0], int):
        p = Path(os.fsdecode(args[0])).absolute().resolve()
        mode, flags = args[1:3]
        write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if write and not inside(p, home):
            raise PermissionError('QA: écriture hors HOME interdite')
        if inside(p, real_home) and not (inside(p, home) or inside(p, repo)):
            raise PermissionError('QA: lecture personnelle interdite')
    if event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate', 'os.utime'):
        paths = args[:1]
    elif event in ('os.rename', 'os.link'):
        paths = args[:2]
    elif event == 'os.symlink':
        paths = args[1:2]
    for raw in paths:
        if not isinstance(raw, int) and not inside(Path(os.fsdecode(raw)).absolute().resolve(), home):
            raise PermissionError('QA: mutation hors HOME interdite')
sys.addaudithook(audit)
'''


class Engine:
    def __init__(self, home):
        self.home = home
        # Environnement minimal : aucun COMPANION_* hérité, aucun jeton hérité.
        env = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'XDG_CONFIG_HOME': str(home/'config'), 'XDG_STATE_HOME': str(home/'state'),
               'XDG_DATA_HOME': str(home/'data'), 'XDG_CACHE_HOME': str(home/'cache'),
               'COMPANION_SHELL_JSON': str(home/'shell-absent.json'),
               'COMPANION_HA_CONFIG': str(home/'ha-absent.json'),
               'COMPANION_HOUSE_CONFIG': str(home/'maison.json'),
               'COMPANION_EXTENSIONS': str(home/'extensions'),
               'PYTHONPATH': str(home/'guard'), 'PYTHONDONTWRITEBYTECODE': '1',
               'PYTHONUNBUFFERED': '1', 'QA_REPO': str(ROOT), 'QA_REAL_HOME': str(Path.home()), 'TMPDIR': str(home)}
        self.err = open(home/'stderr.log', 'a')
        self.p = subprocess.Popen([sys.executable, '-B', str(ROOT/'backend.py')],
                                  cwd=home, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=self.err, text=True)
        self.q = queue.Queue()
        self.events = []
        threading.Thread(target=self.read, daemon=True).start()
        self.initial = self.wait('ready')

    def read(self):
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line))
            except ValueError:
                self.q.put({'event': 'invalid_stdout', 'text': line})

    def wait(self, event, **match):
        until = time.monotonic() + 8
        while time.monotonic() < until:
            try:
                item = self.q.get(timeout=.1)
            except queue.Empty:
                if self.p.poll() is not None:
                    raise AssertionError('moteur arrêté : ' + (self.home/'stderr.log').read_text()[-600:])
                continue
            self.events.append(item)
            if item.get('event') == event and all(item.get(k) == v for k, v in match.items()):
                return item
        raise AssertionError(f'événement absent : {event} {match}')

    def send(self, cmd, **fields):
        assert cmd not in ('ask', 'record', 'greet')
        self.raw(json.dumps({'command': cmd, **fields}))

    def raw(self, line):
        self.p.stdin.write(line+'\n')
        self.p.stdin.flush()

    def ready(self):
        # Barrière : laisser passer le ready différé initial avant toute commande.
        self.send('sync')
        return self.wait('ready')

    def backup(self, cmd, **fields):
        self.send('backup_'+cmd, **fields)
        return self.wait('backup', done=cmd)

    def close(self):
        self.p.stdin.close()
        try:
            self.p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self.p.stdout.close()
        self.err.close()


def check(ok, evidence):
    if not ok:
        raise AssertionError(evidence)


def run():
    results = []
    with tempfile.TemporaryDirectory(prefix='.qa-parcours-', dir=ROOT) as directory:
        home = Path(directory)
        (home/'guard').mkdir()
        (home/'guard/sitecustomize.py').write_text(GUARD)
        (home/'extensions').mkdir()
        engine = Engine(home)
        # Le second ready de démarrage arrive après 0,6 s, avant nos parcours.
        engine.wait('ready')
        persona = home/'.config/omarchy-companion/alison.md'
        roles = home/'config/omarchy-companion/roles'
        exports = {}

        def case(number, title, fn):
            try:
                proof = fn()
                results.append((number, title, 'PASS', proof))
            except Exception as error:
                results.append((number, title, 'FAIL', str(error).replace('\n', ' ')[:350]))

        def fresh():
            r = engine.initial
            check(r['firstRun'] is True and r['config']['mode'] == 'chat' and
                  r['config']['voiceDecide'] is False, 'ready initial non fermé')
            check(not r['roles'] and len(r['examples']) == 3 and 'brainLevel' in r,
                  'roles/examples/brainLevel incorrects')
            check(not any(a['key'] == 'portail' for a in r['access']) and
                  not list((home/'extensions').iterdir()), 'extension détectée')
            return 'ready : firstRun=true, chat, voiceDecide=false, 0 extension, 3 exemples, brainLevel'

        def setup():
            nonlocal engine
            engine.send('save', settings={'setupDone': True})
            r = engine.ready()
            check(r['config']['setupDone'] and not r['firstRun'], 'save setupDone non appliqué')
            # Comme le panneau : shell.json est écrit par le shell, pas par backend.py.
            plugin = json.loads((ROOT/'manifest.json').read_text())['id']
            (home/'shell-absent.json').write_text(json.dumps({'plugins': [{'id': plugin, 'setupDone': True}]}))
            engine.close()
            engine = Engine(home)
            engine.wait('ready')
            check(not engine.initial['firstRun'], 'firstRun revenu après redémarrage')
            return 'save + persistance shell simulée : nouveau moteur, firstRun=false'

        def personality():
            engine.send('persona_save', text='Persona QA uniquement')
            check(engine.wait('persona')['custom'], 'persona_save refusé')
            r = engine.ready()
            check(r['persona'] == {'text': 'Persona QA uniquement', 'custom': True}, 'ready persona incorrect')
            check(persona.stat().st_mode & 0o777 == 0o600, 'persona permissions différentes de 600')
            engine.send('persona_reset')
            check(not engine.wait('persona')['custom'] and not persona.exists(), 'reset incomplet')
            target = home/'persona-cible.txt'
            target.write_text('NE_PAS_LIRE_QA')
            persona.symlink_to(target)
            check(engine.ready()['persona'] == {'text': '', 'custom': False}, 'persona lien lu')
            persona.unlink()
            return 'save/ready custom=true, chmod 600 ; reset ; lien ignoré'

        def examples():
            expected = {x['name']: x for x in engine.initial['examples']}
            for name in ('redaction', 'maison', 'compta-lecture'):
                engine.send('role_example', name=name)
                check(engine.wait('role_saved')['ok'], name+' refusé')
                cards = engine.wait('roles')['items']
                card = next(c for c in cards if c['name'] == name)
                ex = expected[name]
                manifest = json.loads((roles/name/'role.json').read_text())
                allowed = MODES[:MODES.index(ex['ceiling'])+1]
                check(manifest['modes'] == allowed and card['closes'] == [m for m in MODES if m not in allowed]
                      and card['access'] == ex['access'], name+' plafond/accès incorrect')
                engine.send('save', settings={'role': name, 'mode': 'auto'})
                role = engine.wait('role')
                check(role['name'] == name and role['modes'] == allowed, name+' plafond moteur incorrect')
                engine.ready()  # vider les événements associés au save
                engine.send('role_example', name=name)
                check(engine.wait('role_saved')['ok'] is False, name+' doublon accepté')
            engine.send('save', settings={'role': '', 'mode': 'chat'})
            engine.ready()
            return '3 roles émis, plafonds/accès et rôle actif vérifiés ; 3 doublons refusés'

        def backup_export():
            engine.send('save', settings={'mailVault': str(home/'coffre-qa.json'),
                                         'robotUrl': 'https://qa:motdepasse-qa' + '@robot.invalid/?token=X'})
            engine.ready()
            for pointers in (False, True):
                event = engine.backup('export', pointers=pointers)
                check(not event['error'], 'export refusé')
                p = Path(event['path'])
                data = json.loads(p.read_text())
                exports[pointers] = p
                check(p.stat().st_mode & 0o777 == 0o600, 'backup non 600')
                check('motdepasse-qa' not in p.read_text() and '?token=X' not in p.read_text(), 'secret exporté')
                check(('mailVault' in data['settings']) == pointers and
                      ('robotUrl' in data['settings']) == pointers, 'pointeurs incorrects')
            return '2 exports 600 ; mot de passe et token supprimés ; pointeurs sur demande'

        def restore():
            preview = engine.backup('preview', path=str(exports[False]))
            check(not preview['error'] and preview.get('token'), 'aperçu sans token')
            applied = engine.backup('apply', token=preview['token'])
            check(not applied['error'], 'restauration refusée')
            forbidden = {'mode','home','mail','erp','robot','portail','endpoint','provider','keyEnv','voiceDecide'}
            check(not forbidden.intersection(applied['settings']), 'réglages interdits restaurés')
            check(Path(applied['before']).is_file() and 'avant-restauration' in applied['before'], 'backup avant absent')
            p = home/'changed.json'
            p.write_bytes(exports[False].read_bytes())
            preview = engine.backup('preview', path=str(p))
            p.write_text(p.read_text()+' ')
            check(bool(engine.backup('apply', token=preview['token'])['error']), 'fichier changé accepté')
            return 'token appliqué, settings filtrés, avant-restauration présent ; fichier modifié refusé'

        def hostile():
            base = {'format':'alison-backup','version':1,'settings':{},'roles':{}}
            for name, content in [('version', json.dumps(dict(base, version=999))), ('size', ' '* (2*1024*1024))]:
                p = home/(name+'.json'); p.write_text(content)
                check(bool(engine.backup('preview', path=str(p))['error']), name+' accepté')
            link = home/'backup-link.json'; link.symlink_to(exports[False])
            check(bool(engine.backup('preview', path=str(link))['error']), 'backup lien accepté')
            p = home/'hostile.json'
            p.write_text(json.dumps(dict(base, settings={'provider':'pirate','endpoint':'https://pirate.invalid','mode':'auto','home':True},
                roles={'../x':{'persona':'intrus','modes':['chat']},
                       'noncontinu':{'persona':'intrus','modes':['chat','code']}})))
            preview = engine.backup('preview', path=str(p))
            check(not preview['error'], 'hostile non prévisualisable')
            applied = engine.backup('apply', token=preview['token'])
            check(not applied['error'] and len(applied['errors']) == 2 and not applied['settings'], 'hostile non filtré')
            check(not (roles/'noncontinu').exists() and not (roles.parent/'x').exists(), 'rôle hostile écrit')
            return 'version/2 Mo/lien refusés ; ../x et modes troués rejetés ; provider/endpoint ignorés ; écritures confinées'

        def resilience():
            engine.send('commande_inconnue_qa')
            engine.raw('{JSON cassé')
            check(bool(engine.wait('error').get('text')), 'JSON cassé sans erreur')
            check(engine.ready()['event'] == 'ready' and engine.p.poll() is None, 'moteur mort')
            return 'commande inconnue puis JSON cassé : erreur émise, sync→ready, moteur vivant'

        try:
            for i, title, fn in [(1,'Installation neuve',fresh),(2,'setupDone / redémarrage',setup),
                (3,'Personnalité',personality),(4,'Rôles exemples',examples),(5,'Export',backup_export),
                (6,'Restauration',restore),(7,'Fichiers hostiles',hostile),(8,'Entrées invalides',resilience)]:
                case(i,title,fn)
        finally:
            engine.close()
    print('| # | Parcours | Résultat | Preuve |')
    print('|---|---|---|---|')
    for i, title, status, proof in results:
        print(f'| {i} | {title} | {status} | {proof.replace(chr(124), "/")} |')
    failures = [r for r in results if r[2] == 'FAIL']
    print('Défauts : ' + ('aucun observé.' if not failures else 'voir les parcours FAIL (diagnostic fichier:ligne nécessaire).'))
    return bool(failures)


if __name__ == '__main__':
    sys.exit(run())
