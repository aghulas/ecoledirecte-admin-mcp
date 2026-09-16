"""Suivi de l'activation des comptes EcoleDirecte par classe (calcul pur, sans réseau).

Entrées : annuaires complets `utilisateurs/familles` et `utilisateurs/eleves`
(filterSearch vide = tout l'annuaire, confirmé le 16/09/2026 : 529 comptes
famille, 403 élèves).

Rattachement parent ↔ élève : l'API ne donne pas l'id de l'enfant dans
`familles[].enfants`, seulement {nom, prenom, idClasse}. On rapproche donc sur
(nom, prénom, idClasse) normalisés (casse, accents, espaces).
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Any


def _norm(text: Any) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(text.upper().split())


def _child_key(nom: Any, prenom: Any, id_classe: Any) -> tuple[str, str, str]:
    return (_norm(nom), _norm(prenom), str(id_classe))


def _label_person(u: dict[str, Any]) -> str:
    parts = [str(u.get("civilite") or "").strip(), str(u.get("nom") or "").strip(),
             str(u.get("prenom") or "").strip()]
    return " ".join(p for p in parts if p)


def _match_classe(classe: str | None, id_classe: Any, libelle: Any) -> bool:
    if not classe:
        return True
    c = _norm(classe)
    return c == str(id_classe) or c == _norm(libelle) or c.replace(" ", "") == _norm(libelle).replace(" ", "")


def compute_activation(
    familles: list[dict[str, Any]],
    eleves: list[dict[str, Any]],
    classe: str | None = None,
    inclure_noms: bool = False,
) -> dict[str, Any]:
    classes: dict[str, dict[str, Any]] = {}

    def bucket(id_classe: Any, libelle: Any) -> dict[str, Any]:
        key = str(id_classe)
        if key not in classes:
            classes[key] = {
                "idClasse": id_classe,
                "classe": str(libelle or "").strip() or ("(sans classe)" if str(id_classe) in ("0", "", "None") else f"(classe {id_classe})"),
                "_eleves": {},
                "_responsables": {},
            }
        return classes[key]

    for e in eleves:
        if not isinstance(e, dict) or not _match_classe(classe, e.get("idClasse"), e.get("libelleClasse")):
            continue
        b = bucket(e.get("idClasse"), e.get("libelleClasse"))
        b["_eleves"][_child_key(e.get("nom"), e.get("prenom"), e.get("idClasse"))] = e

    # enfant -> comptes responsables rattachés
    parents_of: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in familles:
        if not isinstance(f, dict):
            continue
        for enf in f.get("enfants") or []:
            if not _match_classe(classe, enf.get("idClasse"), enf.get("libelleClasse")):
                continue
            key = _child_key(enf.get("nom"), enf.get("prenom"), enf.get("idClasse"))
            parents_of[key].append(f)
            b = bucket(enf.get("idClasse"), enf.get("libelleClasse"))
            b["_responsables"][f.get("id")] = f
            b["_eleves"].setdefault(key, {"nom": enf.get("nom"), "prenom": enf.get("prenom"),
                                         "_sans_compte_eleve": True})

    rows = []
    for b in classes.values():
        eleves_b = b["_eleves"]
        resp_b = b["_responsables"]
        sans_parent_connecte = []
        sans_responsable = []
        for key, e in eleves_b.items():
            parents = parents_of.get(key, [])
            if not parents:
                sans_responsable.append(e)
            elif not any(p.get("dejaConnecte") for p in parents):
                sans_parent_connecte.append(e)
        resp_jamais = [r for r in resp_b.values() if not r.get("dejaConnecte")]
        row: dict[str, Any] = {
            "idClasse": b["idClasse"],
            "classe": b["classe"],
            "eleves": len(eleves_b),
            "eleves_connectes": sum(1 for e in eleves_b.values() if e.get("dejaConnecte")),
            "responsables": len(resp_b),
            "responsables_connectes": len(resp_b) - len(resp_jamais),
            "eleves_sans_aucun_parent_connecte": len(sans_parent_connecte),
            "eleves_sans_compte_responsable": len(sans_responsable),
        }
        row["taux_activation_familles"] = (
            round(100 * (len(eleves_b) - len(sans_parent_connecte) - len(sans_responsable)) / len(eleves_b), 1)
            if eleves_b else None
        )
        if inclure_noms:
            row["responsables_jamais_connectes"] = sorted(
                (
                    {
                        "id": r.get("id"),
                        "responsable": _label_person(r),
                        "type": r.get("type"),
                        "enfants_dans_la_classe": [
                            f"{str(enf.get('prenom') or '').strip()} {str(enf.get('nom') or '').strip()}"
                            for enf in r.get("enfants") or []
                            if str(enf.get("idClasse")) == str(b["idClasse"])
                        ],
                    }
                    for r in resp_jamais
                ),
                key=lambda x: _norm(x["responsable"]),
            )
            row["eleves_sans_aucun_parent_connecte_noms"] = sorted(
                f"{str(e.get('nom') or '').strip()} {str(e.get('prenom') or '').strip()}"
                for e in sans_parent_connecte
            )
            row["eleves_sans_compte_responsable_noms"] = sorted(
                f"{str(e.get('nom') or '').strip()} {str(e.get('prenom') or '').strip()}"
                for e in sans_responsable
            )
        rows.append(row)

    rows.sort(key=lambda r: _norm(r["classe"]))
    total_eleves = sum(r["eleves"] for r in rows)
    total_sans = sum(r["eleves_sans_aucun_parent_connecte"] + r["eleves_sans_compte_responsable"] for r in rows)
    resp_ids = {f.get("id") for f in familles if isinstance(f, dict) and any(
        _match_classe(classe, enf.get("idClasse"), enf.get("libelleClasse")) for enf in f.get("enfants") or [])}
    resp_connectes = {f.get("id") for f in familles if isinstance(f, dict) and f.get("id") in resp_ids and f.get("dejaConnecte")}
    return {
        "filtre_classe": classe,
        "synthese": {
            "classes": len(rows),
            "eleves": total_eleves,
            "eleves_connectes": sum(r["eleves_connectes"] for r in rows),
            "comptes_responsables": len(resp_ids),
            "comptes_responsables_connectes": len(resp_connectes),
            "eleves_avec_au_moins_un_parent_connecte": total_eleves - total_sans,
            "taux_activation_familles": round(100 * (total_eleves - total_sans) / total_eleves, 1) if total_eleves else None,
        },
        "classes": rows,
        "note": (
            "Élève « activé » = au moins un compte responsable rattaché s'est déjà connecté. "
            "Rapprochement parent↔élève sur nom+prénom+classe (l'API ne fournit pas l'id de l'enfant)."
        ),
    }
