#!/usr/bin/env python3
"""Helper Dolibarr du Compagnon — LECTURE SEULE.

Même principe que `ha.py` et `mail.py` : ce fichier est **le seul** à détenir la clé d'API.
L'agent ne voit jamais la clé, il n'appelle que des verbes. Tout ce qui écrit, valide, envoie ou
supprime **n'existe pas ici** : ces verbes ne sont pas écrits, donc ils ne peuvent pas être appelés,
quoi que demande l'agent ou ce qu'il lit dans une page ou un mail.

  python3 dolibarr.py tester
  python3 dolibarr.py impayes                       créances échues, par ancienneté
  python3 dolibarr.py factures [brouillons|impayees|payees] [n]
  python3 dolibarr.py facture <référence>           détail et lignes
  python3 dolibarr.py client <mots>                 recherche d'un tiers
  python3 dolibarr.py fournisseurs [n]              factures fournisseurs à payer
  python3 dolibarr.py tva <AAAA-MM>                 TVA facturée et déductible du mois
  python3 dolibarr.py ca [AAAA-MM]                  chiffre d'affaires facturé
  python3 dolibarr.py banques                       soldes des comptes

Identifiants : `~/.local/state/omarchy-companion/erp-source.json` (600), écrit par le moteur
d'après les réglages — jamais par l'agent. Il dit OÙ aller chercher (`{"vault": …, "account":
"section.sous-section"}`), et la section doit porter `url` et `api_key`. Le chemin du coffre n'est
pas passé en variable d'environnement : l'agent hérite de l'environnement du moteur, et
`cat $UNE_VARIABLE` échapperait au garde, qui ne lit que le texte des commandes.
"""
import datetime
import json
import texts
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reseau  # noqa: E402
import trousseau  # noqa: E402

STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy-companion"
SOURCE = STATE / "erp-source.json"
TIMEOUT = 25
LIST_MAX = 40
# Statuts de facture Dolibarr : 0 brouillon, 1 validée, 2 payée/close, 3 abandonnée.
STATUTS = {"brouillons": 0, "impayees": 1, "payees": 2}


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def fiscal_month():
    """Mois de début de l'exercice, posé par le moteur dans le pointeur (Réglages). 1 = année civile."""
    try:
        month = json.loads(SOURCE.read_text(encoding="utf-8")).get("fiscal_month", 1)
    except (OSError, ValueError, AttributeError):
        return 1
    return month if isinstance(month, int) and 1 <= month <= 12 else 1


def credentials():
    """URL et clé, ou {} si rien n'est configuré. Jamais affichées, jamais journalisées : la clé est masquée
    dans tout ce que ce programme imprime dès qu'elle est connue."""
    found = _credentials()
    if found:
        trousseau.masquer_sorties(found.get("api_key"))
    return found


def _credentials():
    try:
        pointer = json.loads(SOURCE.read_text(encoding="utf-8"))
        vault, account = str(pointer.get("vault", "")), str(pointer.get("account", ""))
    except (OSError, ValueError, AttributeError):
        return {}
    # Le trousseau du système (18/10) : l'adresse dans le pointeur, la clé dans le trousseau.
    if pointer.get("store") == "keyring":
        data = {"url": str(pointer.get("url", "")), "api_key": trousseau.lire("erp")}
        return data if data["url"] and data["api_key"] else {}
    if not vault or not account:
        return {}
    try:
        data = json.loads(Path(vault).expanduser().read_text(encoding="utf-8"))
        for part in account.split("."):
            data = data[part]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return data if isinstance(data, dict) and data.get("url") and data.get("api_key") else {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Une redirection emporterait la clé (en-tête DOLAPIKEY) vers une autre adresse."""
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def api(path):
    """GET seul. Aucune autre méthode n'est écrite ici : rien ne peut écrire dans Dolibarr."""
    access = credentials()
    if not access:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.dolibarr.0"))
    if not reseau.secret_destination_ok(access["url"]):
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.dolibarr.1"))
    url = str(access["url"]).rstrip("/") + "/api/index.php" + path
    request = urllib.request.Request(url, method="GET",
                                     headers={"DOLAPIKEY": str(access["api_key"]),
                                              "Accept": "application/json"})
    try:
        with OPENER.open(request, timeout=TIMEOUT) as response:
            text = response.read().decode()
            return json.loads(text) if text.strip() else []
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.dolibarr.2"))
        if error.code == 401:
            fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.dolibarr.3"))
        if error.code == 404:
            return []          # « aucun enregistrement trouvé » : ce n'est pas une panne
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.2", code=error.code))
    except urllib.error.URLError as error:
        fail(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.3", reason=error.reason))


def filtre(expression):
    return "sqlfilters=" + urllib.parse.quote(expression)


def euros(value):
    try:
        return f"{float(value or 0):.2f} €"
    except (TypeError, ValueError):
        return "? €"


def jour(stamp):
    try:
        return datetime.date.fromtimestamp(int(stamp)).isoformat()
    except (TypeError, ValueError, OSError):
        return "?"


def total(rows, field):
    return sum(float(row.get(field) or 0) for row in rows)


def mois(texte):
    """« AAAA-MM » -> (début, fin) en DATES. Refuse tout le reste plutôt que de deviner.

    🛑 Les bornes de `sqlfilters` se comparent à des dates écrites `'AAAA-MM-JJ'`, jamais à un
    horodatage : avec un entier, Dolibarr répond 200 et **zéro ligne** — un helper qui dit
    tranquillement « 0 € de TVA » sur un mois plein (mesuré le 20/09, corrigé avant livraison).
    Et c'est `t.datef` : `t.date` fait répondre 503.
    """
    try:
        debut = datetime.date.fromisoformat(texte + "-01")
    except ValueError:
        fail("Mois attendu au format AAAA-MM (par exemple 2026-09).")
    fin = (debut.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return debut.isoformat(), fin.isoformat(), debut


NOMS = {}


def nom_du_tiers(socid):
    """Nom lisible d'un tiers, mis en cache : une liste de factures ne doit pas faire N appels."""
    if not socid:
        return "?"
    if socid not in NOMS:
        fiche = api(f"/thirdparties/{socid}")
        NOMS[socid] = (fiche.get("name") if isinstance(fiche, dict) else None) or f"tiers {socid}"
    return NOMS[socid]


def cmd_tester():
    etat = api("/status")
    version = (etat.get("success", {}) or {}).get("dolibarr_version", "?") if isinstance(etat, dict) else "?"
    print(texts.t(os.environ.get("COMPANION_LANGUAGE", "fr"), "helper.detail.9", version=version))


def cmd_impayes():
    rows = api("/invoices?" + filtre("(t.fk_statut:=:1) and (t.paye:=:0)") + "&limit=200")
    if not rows:
        print("Aucune facture client impayée.")
        return
    today = datetime.date.today()
    lignes = []
    for row in rows:
        echeance = row.get("date_lim_reglement")
        due = None
        try:
            due = datetime.date.fromtimestamp(int(echeance))
        except (TypeError, ValueError, OSError):
            pass
        retard = (today - due).days if due else None
        lignes.append((retard if retard is not None else -9999, row, due))
    lignes.sort(key=lambda x: -x[0])
    print(f"{len(rows)} facture(s) client impayée(s), reste à payer {euros(total(rows, 'remaintopay'))}.")
    for retard, row, due in lignes[:LIST_MAX]:
        age = "non échue" if retard is None or retard < 0 else f"{retard} j de retard"
        print(f"  {row.get('ref','?'):<12} {nom_du_tiers(row.get('socid')):<34} "
              f"{euros(row.get('remaintopay')):>12}  échéance {due.isoformat() if due else '?'} ({age})")


def cmd_factures(quoi="impayees", combien=10):
    if quoi not in STATUTS:
        fail("Choix attendu : brouillons, impayees ou payees.")
    expression = f"(t.fk_statut:=:{STATUTS[quoi]})"
    if quoi == "impayees":
        expression += " and (t.paye:=:0)"
    rows = api("/invoices?" + filtre(expression) + f"&sortfield=t.rowid&sortorder=DESC&limit={int(combien)}")
    if not rows:
        print(f"Aucune facture « {quoi} ».")
        return
    print(f"{len(rows)} facture(s) « {quoi} » (les plus récentes) :")
    for row in rows:
        print(f"  {row.get('ref','?'):<12} {jour(row.get('date')):<11} "
              f"{nom_du_tiers(row.get('socid')):<34} HT {euros(row.get('total_ht')):>11}  "
              f"TTC {euros(row.get('total_ttc')):>11}")


def cmd_facture(reference):
    rows = api("/invoices?" + filtre(f"(t.ref:like:'{reference}')") + "&limit=2")
    if not rows:
        fail(f"Aucune facture « {reference} ».")
    row = rows[0]
    etat = {"0": "brouillon", "1": "validée", "2": "payée", "3": "abandonnée"}.get(str(row.get("statut")), "?")
    print(f"{row.get('ref')} · {nom_du_tiers(row.get('socid'))} · {etat} · date {jour(row.get('date'))}")
    print(f"  HT {euros(row.get('total_ht'))} · TVA {euros(row.get('total_tva'))} · "
          f"TTC {euros(row.get('total_ttc'))} · reste {euros(row.get('remaintopay'))}")
    for ligne in (row.get("lines") or [])[:LIST_MAX]:
        print(f"  - {str(ligne.get('desc') or ligne.get('libelle') or '?')[:60]:<62} "
              f"{ligne.get('qty','?'):>6} × {euros(ligne.get('subprice'))} = {euros(ligne.get('total_ht'))}")


def cmd_client(mots):
    besoin = " ".join(mots).strip().replace("'", "")
    if len(besoin) < 2:
        fail("Donne au moins deux caractères à chercher.")
    rows = api("/thirdparties?" + filtre(f"(t.nom:like:'%{besoin}%')") + "&limit=15")
    if not rows:
        print(f"Aucun tiers pour « {besoin} ».")
        return
    for row in rows:
        print(f"  {str(row.get('code_client') or '-'):<10} {str(row.get('name'))[:40]:<42} "
              f"{str(row.get('town') or ''):<20} id {row.get('id')}")


def cmd_fournisseurs(combien=10):
    # Côté fournisseurs, `fk_statut` ne se lit pas comme côté clients (aucune ligne en statut 1
    # alors que 45 factures sont impayées) : c'est `paye` qui fait foi.
    rows = api("/supplierinvoices?" + filtre("(t.paye:=:0)")
               + f"&sortfield=t.rowid&sortorder=DESC&limit={int(combien)}")
    if not rows:
        print("Aucune facture fournisseur à payer.")
        return
    print(f"{len(rows)} facture(s) fournisseur non payée(s), total {euros(total(rows, 'total_ttc'))} :")
    for row in rows:
        print(f"  {str(row.get('ref') or '?'):<14} {jour(row.get('date')):<11} "
              f"{nom_du_tiers(row.get('socid')):<34} TTC {euros(row.get('total_ttc')):>12}")


def cmd_tva(texte):
    debut, fin, premier = mois(texte)
    ventes = api("/invoices?" + filtre(f"(t.fk_statut:>:0) and (t.datef:>=:'{debut}') and (t.datef:<:'{fin}')") + "&limit=500")
    achats = api("/supplierinvoices?" + filtre(f"(t.datef:>=:'{debut}') and (t.datef:<:'{fin}')") + "&limit=500")
    collectee, deductible = total(ventes, "total_tva"), total(achats, "total_tva")
    print(f"TVA {premier.strftime('%m/%Y')} — sur les factures DATÉES du mois, hors brouillons :")
    print(f"  collectée   {euros(collectee)}   ({len(ventes)} facture(s) client)")
    print(f"  déductible  {euros(deductible)}   ({len(achats)} facture(s) fournisseur)")
    print(f"  solde       {euros(collectee - deductible)}")
    print("  ⚠ Calcul sur les dates de facture. Ce n'est PAS la CA3 : régime, encaissements,")
    print("    autoliquidation et intracom ne sont pas traités ici. À croiser avec le FEC.")


def cmd_ca(texte=None):
    if texte:
        debut, fin, premier = mois(texte)
        periode = premier.strftime("%m/%Y")
    else:
        # Exercice : du 1er du mois réglé (« fiscal_month » du pointeur, janvier par défaut) sur douze mois.
        start = fiscal_month()
        today = datetime.date.today()
        premier = datetime.date(today.year - (0 if today.month >= start else 1), start, 1)
        suivant = premier.replace(year=premier.year + 1)
        debut, fin = premier.isoformat(), suivant.isoformat()
        periode = f"exercice {debut} → {suivant.isoformat()}"
    rows = api("/invoices?" + filtre(f"(t.fk_statut:>:0) and (t.datef:>=:'{debut}') and (t.datef:<:'{fin}')") + "&limit=1000")
    print(f"Chiffre d'affaires facturé, {periode} : {euros(total(rows, 'total_ht'))} HT "
          f"({len(rows)} facture(s), brouillons exclus).")


def cmd_banques():
    rows = api("/bankaccounts?limit=20")
    if not rows:
        print("Aucun compte bancaire.")
        return
    for row in rows:
        print(f"  {str(row.get('label') or row.get('bank') or '?')[:34]:<36} "
              f"solde {euros(row.get('balance')):>14}  ({row.get('account_currency_code') or 'EUR'})")


VERBES = {
    "tester": lambda args: cmd_tester(),
    "impayes": lambda args: cmd_impayes(),
    "factures": lambda args: cmd_factures(*(args[:2] or ["impayees"])),
    "facture": lambda args: cmd_facture(args[0]) if args else fail("Référence attendue."),
    "client": lambda args: cmd_client(args) if args else fail("Mots à chercher attendus."),
    "fournisseurs": lambda args: cmd_fournisseurs(*(args[:1] or [])),
    "tva": lambda args: cmd_tva(args[0]) if args else fail("Mois attendu (AAAA-MM)."),
    "ca": lambda args: cmd_ca(args[0] if args else None),
    "banques": lambda args: cmd_banques(),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in VERBES:
        fail("Verbes : " + ", ".join(sorted(VERBES)) + ".")
    VERBES[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
