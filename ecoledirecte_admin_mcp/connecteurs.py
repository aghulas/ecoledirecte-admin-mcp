"""Applications partenaires (« Mes Applis ») : état réel par public et activation.

Relevé dans le front admin (ConnecteurDetailDirectiveCtrl, 02/10/2026) :
- la liste vient de `connecteurs` (GET) ; chaque connecteur porte son mode
  d'activation (isUniversel, isActivationByEtab, isActivationByCible + cibles,
  isActivationByClasse, isCASAuth, needAPIKey, paramsComplementaires) et ses
  formats de clés de paramètres (formatCleParametreSansCible / MultiCible /
  Specifique, avec %CODE%, %IDETAB%, %CIBLECOURT%) ;
- l'activation n'a pas d'endpoint propre : le front écrit des PARAMÈTRES
  établissement (`<format>Actif` = '1'/'0', un par public si activation par
  public, un par établissement si activation par établissement) via le même
  POST `parametres` que les autres réglages ; pour un connecteur CAS activé par
  établissement, il renseigne aussi `<format>RNE` avec le RNE de l'établissement
  s'il est vide ;
- le champ `isActifEtab` renvoyé par l'API n'est PAS l'état réel (faux pour
  tous les connecteurs alors que 34 sont actifs) : l'état se lit dans les
  paramètres. Beaucoup de connecteurs sont « activés par défaut »
  (activerParDefaut) pour un ou plusieurs publics.

Seuls les connecteurs « universels » (80 sur 87) suivent ce schéma ; les autres
(ESIDOC, CATER, SACOCHE, VOLTAIRE…) ont un écran codé en dur dans le front et
sont hors périmètre de l'écriture.
"""
from __future__ import annotations

from typing import Any

CIBLES = {"F": "Familles", "E": "Élèves", "P": "Enseignants", "A": "Personnels"}
_CIBLES_PAR_NOM = {
    **{k.lower(): k for k in CIBLES},
    **{v.lower(): k for k, v in CIBLES.items()},
    "eleves": "E", "professeurs": "P", "profs": "P", "administratifs": "A",
}
CATEGORIES_ECOLE = {31, 38, 39}  # Niveaux > École, Maternelle, Élémentaire


def code_cible(valeur: str) -> str:
    c = _CIBLES_PAR_NOM.get(str(valeur).strip().lower())
    if not c:
        raise ValueError(f"Public inconnu : {valeur!r} (Familles, Élèves, Enseignants, Personnels — ou F/E/P/A).")
    return c


def cle(conn: dict[str, Any], param: str, multi: bool, id_etab: int, cible: str = "") -> str:
    """Reproduction exacte de getClePourParametre (front admin)."""
    spec = conn.get("formatCleParametreSpecifique")
    if isinstance(spec, dict) and isinstance(spec.get(param), str) and spec[param]:
        fmt = spec[param]
    elif multi and conn.get("isActivationByCible") and conn.get("cibles"):
        fmt = conn.get("formatCleParametreMultiCible") or ""
    else:
        fmt = conn.get("formatCleParametreSansCible") or ""
    fmt = fmt.replace("%CODE%", str(conn.get("code"))).replace("%IDETAB%", str(id_etab))
    return fmt.replace("%CIBLECOURT%", cible) + param


def cles_activation(conn: dict[str, Any], etabs: list[int]) -> list[tuple[str, str]]:
    """[(clé du paramètre Actif, public)] — public '*' si l'activation n'est pas
    par public. Reproduit initListParamsConnecteur pour un connecteur universel."""
    if not conn.get("isUniversel"):
        return []
    tab = list(etabs) if conn.get("isActivationByEtab") else [0]
    out: list[tuple[str, str]] = []
    for e in tab:
        if conn.get("isActivationByCible") and conn.get("cibles"):
            out += [(cle(conn, "Actif", True, e, c), c) for c in conn["cibles"]]
        else:
            out.append((cle(conn, "Actif", True, e), "*"))
    return out


def _labels_categories(arbre: list[dict[str, Any]]) -> dict[int, str]:
    out: dict[int, str] = {}

    def walk(n: dict[str, Any]) -> None:
        out[n.get("id")] = n.get("libelle")
        for ch in n.get("tabChildren") or []:
            walk(ch)

    for n in arbre or []:
        walk(n)
    return out


def donnees_partagees(conn: dict[str, Any], rgpd: list[dict[str, Any]]) -> dict[str, list[str]]:
    lib = {r.get("code"): r.get("libelle") for r in rgpd or []}
    out: dict[str, list[str]] = {}
    for r in conn.get("tabRGPD") or []:
        out.setdefault(CIBLES.get(r.get("typeUser"), r.get("typeUser")), []).append(lib.get(r.get("rgpdData"), r.get("rgpdData")))
    return {k: sorted(v) for k, v in sorted(out.items())}


def etat(conn: dict[str, Any], valeurs: dict[str, Any], etabs: list[int]) -> dict[str, bool] | None:
    """{public lisible: actif} ; None pour un connecteur non universel."""
    ks = cles_activation(conn, etabs)
    if not ks:
        return None
    res: dict[str, bool] = {}
    for k, c in ks:
        nom = "Tous" if c == "*" else CIBLES.get(c, c)
        res[nom] = res.get(nom, False) or str(valeurs.get(k)) == "1"
    return res


def ligne(conn: dict[str, Any], valeurs: dict[str, Any], etabs: list[int], categories: dict[int, str],
          rgpd: list[dict[str, Any]], detail: bool = False) -> dict[str, Any]:
    st = etat(conn, valeurs, etabs)
    cats = [c for c in conn.get("categories") or [] if isinstance(c, int)]
    row: dict[str, Any] = {
        "code": conn.get("code"),
        "libelle": (conn.get("libelle") or "").strip(),
        "actif": bool(st and any(st.values())),
        "etat_par_public": st if st is not None else "écran spécifique (non universel) — voir l'admin",
        "active_par_defaut": bool(conn.get("activerParDefaut")),
        "niveaux": [categories.get(c) for c in cats if 31 <= c <= 49 or c in (35, 36, 37)] or None,
        "adapte_ecole": bool(CATEGORIES_ECOLE & set(cats)),
        "premium": bool(conn.get("isPremium")),
        "donnees_partagees": donnees_partagees(conn, rgpd),
    }
    contraintes = []
    if conn.get("needAPIKey"):
        contraintes.append("clé d'API fournie par l'éditeur")
    if conn.get("isActivationByClasse"):
        contraintes.append("activation par classe")
    if conn.get("paramsComplementaires"):
        contraintes.append("paramètres complémentaires : " + ", ".join(p.get("libelle", "?") for p in conn["paramsComplementaires"]))
    if conn.get("isCASAuth"):
        contraintes.append("authentification CAS (RNE de l'établissement)")
    if contraintes:
        row["contraintes"] = contraintes
    if detail:
        row.update({
            "description": conn.get("description"),
            "info_administrateur": (conn.get("infoAdministrateur") or "").strip() or None,
            "publics_possibles": [CIBLES.get(c, c) for c in conn.get("cibles") or []],
            "categories": [categories.get(c, c) for c in cats],
            "site": conn.get("urlSiteConnecteur") or None,
            "cles_parametres": [k for k, _ in cles_activation(conn, etabs)],
            "activation_par_etablissement": bool(conn.get("isActivationByEtab")),
        })
    return row


def plan_activation(conn: dict[str, Any], valeurs: dict[str, Any], etabs_info: list[dict[str, Any]],
                    actif: bool, cibles: list[str] | None, rgpd: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcule les écritures à faire (sans rien écrire). Lève ValueError si le
    connecteur ne peut pas être (dés)activé proprement par cet outil."""
    if not conn.get("isUniversel"):
        raise ValueError(f"{conn.get('libelle')!r} a un écran spécifique dans l'admin (non universel) — à régler à la main.")
    if actif:
        if conn.get("needAPIKey"):
            raise ValueError("Ce connecteur exige une clé d'API fournie par l'éditeur — activation à faire dans l'admin.")
        if conn.get("isActivationByClasse"):
            raise ValueError("Ce connecteur s'active classe par classe — activation à faire dans l'admin.")
        if conn.get("paramsComplementaires"):
            raise ValueError("Ce connecteur demande des paramètres complémentaires (n° d'abonné…) — activation à faire dans l'admin.")
    etabs = [int(e["id"]) for e in etabs_info if e.get("id") not in (None, 0)]
    ks = cles_activation(conn, etabs)
    possibles = {c for _, c in ks}
    if cibles:
        voulues = {code_cible(c) for c in cibles}
        if "*" in possibles:
            raise ValueError("Ce connecteur ne s'active pas public par public : ne pas préciser de public.")
        hors = voulues - possibles
        if hors:
            raise ValueError(f"Public(s) non proposé(s) par ce connecteur : {', '.join(CIBLES[c] for c in hors)}.")
    else:
        voulues = possibles
    cible_val = "1" if actif else "0"
    changements = []
    for k, c in ks:
        if c not in voulues:
            continue
        avant = valeurs.get(k)
        changements.append({"libelle": k, "public": "Tous" if c == "*" else CIBLES.get(c, c),
                            "avant": avant, "apres": cible_val, "change": str(avant) != cible_val})
    if actif and conn.get("isCASAuth") and conn.get("isActivationByEtab"):
        for e in etabs_info:
            if e.get("id") in (None, 0) or not e.get("RNE"):
                continue
            k = cle(conn, "RNE", False, int(e["id"]))
            avant = valeurs.get(k)
            if avant in (None, "", "0", 0, False):
                changements.append({"libelle": k, "public": "RNE (CAS)", "avant": avant, "apres": e["RNE"], "change": True})
    partages = donnees_partagees(conn, rgpd)
    publics = {ch["public"] for ch in changements if ch["change"] and ch["apres"] == "1"}
    return {
        "code": conn.get("code"),
        "libelle": (conn.get("libelle") or "").strip(),
        "action": "activation" if actif else "désactivation",
        "changements": changements,
        "a_ecrire": [ch for ch in changements if ch["change"]],
        **({"donnees_transmises_a_l_editeur": {p: v for p, v in partages.items() if p in publics or "Tous" in publics}}
           if actif and publics else {}),
    }
