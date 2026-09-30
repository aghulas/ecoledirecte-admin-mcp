"""Régénère le catalogue des paramètres établissement à partir du front admin.

Le serveur `parametres` de l'API renvoie « 0 » pour un libellé qui n'existe pas,
sans erreur : impossible de découvrir les libellés par l'API. On les relève donc
dans le JavaScript public de admin.ecoledirecte.com (bundle `scripts/scripts.*.js`),
là où chaque écran de paramétrage les demande (`{libelle: "..."}`,
`tabParametres["..."]`).

Usage :
    python tools/extraire_parametres.py                 # télécharge le bundle courant
    python tools/extraire_parametres.py --bundle s.js   # à partir d'un fichier local

Écrit `ecoledirecte_admin_mcp/data/parametres_front.json`. Les libellés
construits dynamiquement sont résolus ainsi :
  - indice d'établissement → 0 (établissement unique / paramétrage commun) ;
  - `realTypeUser` / `typeUser` → les valeurs affectées dans le MÊME contrôleur
    (marqués `certain: false`, car un écran peut ne demander un paramètre que
    pour l'un des profils) ;
  - autres variables (jour, code de porte-monnaie, id de classe…) → motif
    générique `{variable}` dans la liste `motifs`.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import itertools
import json
import re
import httpx
from pathlib import Path

BASE = "https://admin.ecoledirecte.com/"
UA = "Mozilla/5.0 (Macintosh) ecoledirecte-admin-mcp/extraire_parametres"
SORTIE = Path(__file__).resolve().parents[1] / "ecoledirecte_admin_mcp" / "data" / "parametres_front.json"

TOK = r'(?:"[^"\n]*"|[A-Za-z_$][\w$]*(?:\.[\w$]+|\[[^\]]*\])*(?:\(\))?)'
EXPR = re.compile(r'(?:libelle:|tabParametres\[|tabParametresToSend\[|data\[)\s*(' + TOK + r'(?:\s*\+\s*' + TOK + r')*)')
ETAB_VARS = {"indiceEtab", "idEtablissement", "idEtab"}


def _get(url: str) -> str:
    # httpx (dépendance du projet) embarque les certificats via certifi, contrairement
    # à urllib avec le Python de python.org sur macOS.
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def telecharger_bundle() -> tuple[str, str]:
    index = _get(BASE)
    m = re.search(r'src="(scripts/scripts\.[0-9a-f]+\.js)"', index)
    if not m:
        raise SystemExit("Bundle scripts.*.js introuvable dans la page admin.")
    return m.group(1), _get(BASE + m.group(1))


def extraire(js: str) -> tuple[dict, list]:
    ctrls = [(m.start(), m.group(1)) for m in re.finditer(r'\.controller\("(\w+)"', js)]
    bornes = [p for p, _ in ctrls] + [len(js)]

    def controleur(pos: int) -> tuple[str | None, int]:
        nom, debut = None, 0
        for p, n in ctrls:
            if p > pos:
                break
            nom, debut = n, p
        return nom, debut

    cache: dict[int, tuple[list, list]] = {}

    def types_du_controleur(debut: int) -> tuple[list, list]:
        if debut not in cache:
            fin = next((b for b in bornes if b > debut), len(js))
            corps = js[debut:fin]
            reel = sorted(set(re.findall(r'realTypeUser="([^"]+)"', corps)))
            typ = sorted(set(re.findall(r'typeUser==="([a-z]+)"', corps)) | set(re.findall(r'typeUser="([a-z]+)"', corps)))
            cache[debut] = (reel, typ)
        return cache[debut]

    libelles: dict[str, dict] = {}
    motifs: dict[str, set] = collections.defaultdict(set)
    for m in EXPR.finditer(js):
        parts = re.findall(TOK, m.group(1))
        if not any(p.startswith('"') for p in parts):
            continue
        nom_ctrl, debut = controleur(m.start())
        reel, typ = types_du_controleur(debut)
        choix, certain, motif = [], True, False
        for p in parts:
            if p.startswith('"'):
                choix.append([p[1:-1]])
                continue
            var = p.split(".")[-1].split("[")[0].replace("()", "")
            if var in ETAB_VARS or "tabEtablissements" in p:
                choix.append(["0"])
            elif var == "realTypeUser" and reel:
                choix.append(reel); certain = certain and len(reel) == 1
            elif var == "typeUser" and typ:
                choix.append(typ); certain = certain and len(typ) == 1
            else:
                choix.append(["{" + var + "}"]); motif = True
        for combo in itertools.product(*choix):
            lib = "".join(combo)
            if "/" not in lib or not lib[0].isupper() or lib.endswith(("/", "_")):
                continue
            if " (UTC" in lib:
                # Libellés de la liste des fuseaux horaires (« Europe/Paris (UTC+1) »),
                # pas des paramètres : la valeur est dans Sites/FuseauHoraire.
                continue
            if motif:
                motifs[lib].add(nom_ctrl or "?")
                continue
            e = libelles.setdefault(lib, {"controleurs": set(), "certain": False, "base64": False})
            e["controleurs"].add(nom_ctrl or "?")
            e["certain"] = e["certain"] or certain
            # `{libelle: ..., encoded: true}` : valeur stockée en base64 (adresse, présentation…)
            e["base64"] = e["base64"] or js[m.end():m.end() + 12].startswith(",encoded:!0")
    libs = {k: {"controleurs": sorted(v["controleurs"]), "certain": v["certain"],
                **({"base64": True} if v["base64"] else {})} for k, v in sorted(libelles.items())}
    mots = [{"motif": k, "controleurs": sorted(v)} for k, v in sorted(motifs.items())]
    return libs, mots


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bundle", help="fichier scripts.*.js local (sinon téléchargé)")
    args = ap.parse_args()
    if args.bundle:
        source, js = Path(args.bundle).name, Path(args.bundle).read_text(encoding="utf-8")
    else:
        source, js = telecharger_bundle()
    libs, mots = extraire(js)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "source": source,
        "date_extraction": dt.date.today().isoformat(),
        "nb_libelles": len(libs),
        "libelles": libs,
        "motifs": mots,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(libs)} libellés ({sum(v['certain'] for v in libs.values())} certains), {len(mots)} motifs → {SORTIE}")


if __name__ == "__main__":
    main()
