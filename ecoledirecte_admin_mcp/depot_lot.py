"""Dépôt par lot des fiches d'une classe dans une liste de pièces à verser.

Usage (depuis la racine du dépôt, venv activé) :
  ED_ADMIN_DEPOT_RACINE=<dossier des fiches par classe> \\
  python -m ecoledirecte_admin_mcp.depot_lot --classe CM2B            # simulation
  ED_ADMIN_DEPOT_ACTIF=1 ED_ADMIN_DEPOT_RACINE=... \\
  python -m ecoledirecte_admin_mcp.depot_lot --classe CM2B --confirm  # dépôt réel

Le dossier <racine>/<CLASSE>/ contient un PDF par élève nommé
CLASSE_NOM_Prenom.pdf (les PDF groupés « … Fiches … » sont ignorés).
Chaque fichier est rapproché d'un élève ACTIF de la classe EcoleDirecte
correspondante (nom exact + prénom, tolérance sur prénom tronqué). Tout fichier
non rapproché ou ambigu est SIGNALÉ et jamais déposé.

Idempotent : un élève qui a déjà un dépôt est sauté (jamais remplacé) — on peut
relancer le script après une coupure. Bilan écrit en CSV à côté du journal.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .client import EcoleDirecteAdminClient
from .depot_pieces import JOURNAL, DepotError, deposer_piece


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^A-Z]", "", "".join(c for c in s if not unicodedata.combining(c)).upper())


def _classe_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).upper())


def rapprocher(fichiers: list[Path], eleves_classe: list[dict]) -> tuple[list, list]:
    """→ (appariés [(fichier, eleve)], anomalies [(fichier, raison)])."""
    ok, ko, pris = [], [], {}
    for f in fichiers:
        parts = f.stem.split("_", 2)
        if len(parts) < 3:
            ko.append((f, "nom de fichier non conforme"))
            continue
        nom, pre = _n(parts[1]), _n(parts[2])
        cands = [e for e in eleves_classe if _n(e["nom"]) == nom
                 and (_n(e["prenom"]).startswith(pre) or pre.startswith(_n(e["prenom"])))]
        if len(cands) != 1:
            ko.append((f, "aucun élève correspondant" if not cands else "plusieurs élèves possibles"))
            continue
        e = cands[0]
        if e["id"] in pris:
            ko.append((f, f"doublon avec {pris[e['id']].name}"))
            continue
        pris[e["id"]] = f
        ok.append((f, e))
    return ok, ko


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classe", required=True, help="nom du sous-dossier, ex. CM2B")
    ap.add_argument("--libelle-ed", help="libellé EcoleDirecte si différent (ex. 'PS/MS')")
    ap.add_argument("--confirm", action="store_true", help="dépôt réel (sinon simulation)")
    ap.add_argument("--pause", type=float, default=3.0, help="secondes entre deux dépôts")
    args = ap.parse_args()

    racine = Path(os.environ["ED_ADMIN_DEPOT_RACINE"])
    dossier = racine / args.classe
    fichiers = sorted(p for p in dossier.glob("*.pdf") if "Fiches" not in p.name and "_" in p.name)

    c = EcoleDirecteAdminClient()
    try:
        eleves = await c.list_utilisateurs("eleves", "")
        familles = await c.list_utilisateurs("familles", "")
        cible = _classe_key(args.libelle_ed or args.classe)
        classe = [e for e in eleves if _classe_key(e.get("libelleClasse", "")) == cible]
        if not classe:
            raise SystemExit(f"Classe EcoleDirecte introuvable pour '{args.classe}'.")
        ok, ko = rapprocher(fichiers, classe)
        sans_fichier = [e for e in classe if e["id"] not in {x[1]["id"] for x in ok}]

        print(f"Classe {classe[0].get('libelleClasse')} : {len(classe)} élèves, "
              f"{len(fichiers)} PDF, {len(ok)} rapprochés, {len(ko)} anomalies, "
              f"{len(sans_fichier)} élèves sans fichier.")
        for f, raison in ko:
            print(f"  ⚠️  {f.name} : {raison}")
        for e in sans_fichier:
            print(f"  ◻️  sans fichier : {e['nom']} {e['prenom']}")
        print(("DÉPÔT RÉEL" if args.confirm else "SIMULATION") + " —", len(ok), "fichiers\n")

        bilan = []
        for i, (f, e) in enumerate(ok, 1):
            try:
                r = await deposer_piece(c, e["id"], str(f), confirm=args.confirm,
                                        eleves=eleves, familles=familles)
                etat = ("déposé" if r.get("depot_effectue") else
                        "déjà présent" if r.get("deja_depose") else "simulé")
            except DepotError as exc:
                etat, r = f"ERREUR : {exc}", {}
            print(f"[{i:2}/{len(ok)}] {e['nom']} {e['prenom']:<20} → {etat}")
            bilan.append({"classe": e.get("libelleClasse"), "id_eleve": e["id"],
                          "eleve": f"{e['nom']} {e['prenom']}", "fichier": f.name, "etat": etat})
            if args.confirm and etat == "déposé":
                await asyncio.sleep(args.pause)

        out = JOURNAL.parent / f"bilan_{args.classe}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(bilan[0].keys()) if bilan else ["etat"])
            w.writeheader()
            w.writerows(bilan)
        from collections import Counter
        print("\nBilan :", dict(Counter(b["etat"].split(" :")[0] for b in bilan)), "→", out)
    finally:
        await c.aclose()


if __name__ == "__main__":
    asyncio.run(main())
