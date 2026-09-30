"""Demandes de modification AU NOM D'UNE FAMILLE (activités, régime, téléphones,
mails et téléphones des parents)
via la supervision admin — ÉCRITURE, exception n°3 (30/09/2026).

Reproduit les formulaires de l'espace famille (relevés sur le front famille et
utilisés pour ~700 demandes à la rentrée 2026, scripts ~/dev/fiches-forfaits) :
  - activités / régime d'un élève (« Vos informations ») :
      POST v3/demandemodifications/eleve.awp?verbe=post
      data={"modifications": {"id", "idEtablissement", "prenom", "activites":[…], "idRegime"?}}
      (seules les activités à changer sont envoyées ; jours : jour1=L, jour2=M, jour4=J, jour5=V ;
       la cantine a le type « Repas ») ;
  - coordonnées de la famille (téléphones) :
      POST v3/demandemodifications/coordonnees.awp?verbe=post
      data={"modifications": {"contenu": base64(XML COMPLET de la fiche)}} — réplique
      de modifsToXml du front : tous les champs sont recopiés à l'identique, seuls les
      téléphones changent ;
  - mails / téléphones des parents (« contacts », 30/09/2026) : même demande de
      coordonnées, seuls les champs demandés (mailPerso, mailTravail, telMobile,
      telTravail, telDomicile du responsable ou du conjoint) changent.
Les demandes arrivent dans Charlemagne, où le secrétariat les valide (rien n'est
modifié directement dans la base).

Garde-fous :
  - sans confirm=True : SIMULATION — la fiche est LUE (supervision en lecture) pour
    calculer ce qui changerait, mais aucune demande n'est envoyée ;
  - écriture activée seulement si ED_ADMIN_DEMANDES_ACTIF=1 (jamais sur Azure) ;
  - types autorisés : ED_ADMIN_DEMANDES_TYPES (défaut « activites,regime,telephones,contacts ») ;
  - activités : un code doit déjà figurer sur la fiche de l'élève, ou dans
    ED_ADMIN_DEMANDES_ACTIVITES (codes séparés par « | ») ;
  - refus si une demande est déjà en attente pour l'élève (activités/régime) ou pour
    la famille (coordonnées) — on ne superpose jamais deux demandes ;
  - téléphones : seuls les numéros français reconnus sont reformatés ; les autres
    (étrangers, mentions, plusieurs numéros) sont signalés, jamais modifiés ;
  - contacts : champs limités à la liste CHAMPS_CONTACT ; téléphone français valide
    (mis au format « 06 12 34 56 78 »), mail valide ; jamais de valeur vide (effacer
    une coordonnée se fait dans Charlemagne) ; l'adresse n'est jamais modifiée ;
  - JAMAIS de demande sur le mode de règlement ni les coordonnées bancaires : la
    demande « mode de règlement » du site renvoie systématiquement l'IBAN complet ;
    ces informations se saisissent uniquement dans Charlemagne par le secrétariat ;
  - chaque demande envoyée est journalisée (CSV local, sans jeton).
"""
from __future__ import annotations

import base64
import csv
import json
import os
import re
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from .config import SETTINGS
from .depot_pieces import DepotError, choisir_compte, ouvrir_supervision, resoudre_eleve_famille

JOURNAL = SETTINGS.home_dir / "demandes.csv"
JOURS = {"L": "jour1", "M": "jour2", "J": "jour4", "V": "jour5"}
TYPE_ACTIVITE = {"MIDI": "Repas"}
TEL_OK = re.compile(r"^\d{2} \d{2} \d{2} \d{2} \d{2}$")
CHAMPS_TEL = {"responsable": ("telMobile", "telTravail", "telDomicile"), "conjoint": ("telMobile", "telTravail")}
CHAMPS_MAIL = {"responsable": ("mailPerso", "mailTravail"), "conjoint": ("mailPerso", "mailTravail")}
CHAMPS_CONTACT = {b: CHAMPS_MAIL[b] + CHAMPS_TEL[b] for b in CHAMPS_TEL}
MAIL_OK = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


class DemandeError(DepotError):
    """Erreur de demande de modification (message transmis tel quel)."""


def _demandes_actives() -> bool:
    return os.environ.get("ED_ADMIN_DEMANDES_ACTIF", "") == "1"


def _types_autorises() -> set[str]:
    raw = os.environ.get("ED_ADMIN_DEMANDES_TYPES", "activites,regime,telephones,contacts")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _activites_supplementaires() -> set[str]:
    return {x.strip().upper() for x in os.environ.get("ED_ADMIN_DEMANDES_ACTIVITES", "").split("|") if x.strip()}


def _exiger_type(t: str) -> None:
    if t not in _types_autorises():
        raise DemandeError(f"Type de demande « {t} » non autorisé (ED_ADMIN_DEMANDES_TYPES).")


def _journaliser(row: dict[str, Any]) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    new = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


# ----------------------------------------------------------------------
# Activités / régime (fonctions pures, testées sans réseau)
# ----------------------------------------------------------------------
def jours_actuels(activites: list[dict], code: str) -> str:
    a = next((x for x in activites if x.get("code") == code), None)
    return "".join(k for k, j in JOURS.items() if a and a.get(j)) if a else ""


def normaliser_jours(jours: str) -> str:
    j = (jours or "").upper().replace(" ", "").replace(",", "")
    if any(c not in JOURS for c in j):
        raise DemandeError(f"Jours invalides « {jours} » : utiliser L, M, J, V (ex. « LMJV », « » pour aucun).")
    return "".join(k for k in JOURS if k in j)


def construire_modif_eleve(eleve_ed: dict[str, Any], activites: dict[str, str] | None,
                           regime: int | None) -> tuple[dict[str, Any] | None, list[str]]:
    """→ (corps de la demande ou None si déjà conforme, changements lisibles)."""
    actuelles = eleve_ed.get("activites") or []
    connus = {a.get("code") for a in actuelles} | _activites_supplementaires()
    acts, changements = [], []
    for code, cible in (activites or {}).items():
        code = code.upper()
        if code not in connus:
            raise DemandeError(f"Activité « {code} » inconnue sur la fiche de l'élève "
                               f"(connues : {', '.join(sorted(c for c in connus if c))}).")
        cible = normaliser_jours(cible)
        avant = jours_actuels(actuelles, code)
        if avant != cible:
            a = {"code": code, "type": TYPE_ACTIVITE.get(code, "")}
            a.update({f"jour{i}": False for i in range(1, 8)})
            a.update({JOURS[k]: True for k in cible})
            acts.append(a)
            changements.append(f"{code} : {avant or 'aucun jour'} → {cible or 'aucun jour'}")
    modif = {"id": eleve_ed.get("id"), "idEtablissement": eleve_ed.get("idEtablissement"),
             "prenom": eleve_ed.get("prenom"), "activites": acts}
    if regime is not None and eleve_ed.get("idRegime") != int(regime):
        modif["idRegime"] = int(regime)
        changements.append(f"régime : {eleve_ed.get('idRegime')} → {int(regime)}")
    return (modif if changements else None), changements


async def demande_activites(admin_client, id_eleve: int, activites: dict[str, str] | None = None,
                            regime: int | None = None, confirm: bool = False,
                            compte_id: int | None = None) -> dict[str, Any]:
    if activites:
        _exiger_type("activites")
    if regime is not None:
        _exiger_type("regime")
    if not activites and regime is None:
        raise DemandeError("Rien à demander : indiquer des activités et/ou un régime.")
    res = await resoudre_eleve_famille(admin_client, id_eleve)
    compte = choisir_compte(res, compte_id)
    fam = await ouvrir_supervision(admin_client, compte)
    try:
        d = (await fam.appeler("famillecoordonnees", "get")).get("data") or {}
        eleve_ed = next((e for e in d.get("eleves", []) if int(e.get("id", -1)) == int(id_eleve)), None)
        if not eleve_ed:
            raise DemandeError("Élève absent de la fiche famille (compte non rattaché ?).")
        modif, changements = construire_modif_eleve(eleve_ed, activites, regime)
        apercu = {"eleve": f"{res['eleve']['nom']} {res['eleve']['prenom']} ({res['eleve'].get('libelleClasse')})",
                  "compte_famille": f"{compte['nom']} {compte['prenom']} (id {compte['id']})", "changements": changements}
        if modif is None:
            return {**apercu, "demande_envoyee": False, "message": "Déjà conforme : aucune demande nécessaire."}
        att = (await fam.appeler(f"demandemodifications/coordonnees/{compte['id']}", "get")).get("data") or {}
        if int(id_eleve) in {int(x.get("idEleve", -1)) for x in (att.get("eleves") or [])}:
            return {**apercu, "demande_envoyee": False, "deja_en_attente": True,
                    "message": "Une demande est déjà en attente pour cet élève : la faire valider dans Charlemagne d'abord."}
        if not confirm:
            return {**apercu, "demande_envoyee": False, "corps": modif,
                    "message": "Simulation : rien n'a été envoyé. Rappeler avec confirm=True."}
        if not _demandes_actives():
            raise DemandeError("Écriture désactivée (ED_ADMIN_DEMANDES_ACTIF≠1).")
        r = await fam.appeler("demandemodifications/eleve", "post", {"modifications": modif})
        ok = r.get("code") == 200
        _journaliser({"horodatage": datetime.now().isoformat(timespec="seconds"), "type": "eleve",
                      "id_eleve": id_eleve, "eleve": apercu["eleve"], "id_compte_famille": compte["id"],
                      "changements": " ; ".join(changements), "corps": json.dumps(modif, ensure_ascii=False),
                      "code_api": r.get("code")})
        if not ok:
            raise DemandeError(f"Demande refusée (code {r.get('code')} — {r.get('message') or ''}).")
        return {**apercu, "demande_envoyee": True,
                "message": "Demande envoyée : à valider dans Charlemagne, puis resynchroniser EcoleDirecte."}
    finally:
        await fam.http.aclose()


# ----------------------------------------------------------------------
# Téléphones de la famille (fonctions pures, testées sans réseau)
# ----------------------------------------------------------------------
def normaliser_telephone(v: str | None) -> tuple[str, str]:
    """→ (valeur, statut) ; statut ∈ conforme | corrigé | exception | vide."""
    v0 = (v or "").strip()
    if not v0:
        return v0, "vide"
    if TEL_OK.match(v0):
        return v0, "conforme"
    d = re.sub(r"\D", "", v0)
    if re.fullmatch(r"0033[1-9]\d{8}", d):
        d = "0" + d[4:]
    elif re.fullmatch(r"33[1-9]\d{8}", d) and v0.startswith(("+33", "33")):
        d = "0" + d[2:]
    if re.fullmatch(r"0[1-9]\d{8}", d) and not re.search(r"[A-Za-z/]", v0):
        return " ".join(d[i:i + 2] for i in range(0, 10, 2)), "corrigé"
    return v0, "exception"


def analyser_telephones(d: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    tels, lignes = {"responsable": {}, "conjoint": {}}, []
    for bloc, champs in CHAMPS_TEL.items():
        p = d.get(bloc) or {}
        for ch in champs:
            nv, st = normaliser_telephone(p.get(ch))
            tels[bloc][ch] = nv
            if st in ("corrigé", "exception"):
                lignes.append({"personne": f"{p.get('civilite', '')} {p.get('nomSimple') or p.get('nom', '')} {p.get('prenom', '')}".strip(),
                               "bloc": bloc, "champ": ch, "avant": p.get(ch), "apres": nv, "statut": st})
    return tels, lignes


def xml_coordonnees(d: dict[str, Any], tels: dict[str, dict[str, str]],
                    mails: dict[str, dict[str, str]] | None = None) -> str:
    """Réplique exacte de modifsToXml du front famille (ordre des balises compris).
    `mails` = mails remplacés (par bloc) ; les autres champs sont recopiés tels quels."""
    R = {**(d.get("responsable") or {}), **((mails or {}).get("responsable") or {})}
    C = {**(d.get("conjoint") or {}), **((mails or {}).get("conjoint") or {})}
    sf = (d.get("situationFamiliale") or {"code": 0}).get("code", 0)
    t = lambda tag, val: f"<{tag}>{escape(str(val if val is not None else ''))}</{tag}>"
    parts = [t("adresse1", d.get("adresseLigne1", "")), t("adresse2", d.get("adresseLigne2", "")),
             t("adresse3", d.get("adresseLigne3", "")), t("codePostal", d.get("codePostal", "")),
             t("ville", d.get("ville", "")), t("situationFamiliale", sf),
             t("conjointMailPerso", C.get("mailPerso", "")), t("conjointMailTravail", C.get("mailTravail", "")),
             t("conjointNom", C.get("nom", "")), t("conjointTelMobile", tels["conjoint"]["telMobile"]),
             t("conjointTelTravail", tels["conjoint"]["telTravail"]),
             t("conjointCSP", (C.get("csp") or {}).get("code", "")), t("conjointProfession", C.get("profession", "")),
             t("conjointSociete", C.get("societe", "")),
             t("responsableMailPerso", R.get("mailPerso", "")), t("responsableMailTravail", R.get("mailTravail", "")),
             t("responsableNom", R.get("nom", "")), t("responsableTelMobile", tels["responsable"]["telMobile"]),
             t("responsableTelTravail", tels["responsable"]["telTravail"]),
             t("responsableTelDomicile", tels["responsable"]["telDomicile"]),
             t("responsableCSP", (R.get("csp") or {}).get("code", "")),
             t("responsableProfession", R.get("profession", "")), t("responsableSociete", R.get("societe", ""))]
    return "<demandeModifications>" + "".join(parts) + "</demandeModifications>"


async def demande_telephones(admin_client, compte_id: int, confirm: bool = False) -> dict[str, Any]:
    _exiger_type("telephones")
    familles = await admin_client.list_utilisateurs("familles", "")
    compte = next((f for f in familles if int(f.get("id", -1)) == int(compte_id)), None)
    if not compte:
        raise DemandeError(f"Compte famille {compte_id} introuvable.")
    fam = await ouvrir_supervision(admin_client, compte)
    try:
        d = (await fam.appeler("famillecoordonnees", "get")).get("data") or {}
        tels, lignes = analyser_telephones(d)
        corr = [l for l in lignes if l["statut"] == "corrigé"]
        exc = [l for l in lignes if l["statut"] == "exception"]
        apercu = {"compte_famille": f"{compte['nom']} {compte['prenom']} (id {compte['id']})",
                  "corrections": [f"{l['personne']} {l['champ']} : {l['avant']} → {l['apres']}" for l in corr],
                  "a_traiter_a_la_main": [f"{l['personne']} {l['champ']} : {l['avant']}" for l in exc]}
        if not corr:
            return {**apercu, "demande_envoyee": False, "message": "Aucun numéro à reformater automatiquement."}
        att = (await fam.appeler(f"demandemodifications/coordonnees/{compte['id']}", "get")).get("data") or {}
        if att.get("id"):
            return {**apercu, "demande_envoyee": False, "deja_en_attente": True,
                    "message": "Une demande de coordonnées est déjà en attente pour cette famille."}
        if not confirm:
            return {**apercu, "demande_envoyee": False, "message": "Simulation : rien n'a été envoyé. Rappeler avec confirm=True."}
        if not _demandes_actives():
            raise DemandeError("Écriture désactivée (ED_ADMIN_DEMANDES_ACTIF≠1).")
        contenu = base64.b64encode(xml_coordonnees(d, tels).encode("utf-8")).decode()
        r = await fam.appeler("demandemodifications/coordonnees", "post", {"modifications": {"contenu": contenu}})
        ok = r.get("code") == 200
        _journaliser({"horodatage": datetime.now().isoformat(timespec="seconds"), "type": "coordonnees",
                      "id_eleve": "", "eleve": "", "id_compte_famille": compte["id"],
                      "changements": " ; ".join(apercu["corrections"]), "corps": "(XML complet, téléphones reformatés)",
                      "code_api": r.get("code")})
        if not ok:
            raise DemandeError(f"Demande refusée (code {r.get('code')} — {r.get('message') or ''}).")
        return {**apercu, "demande_envoyee": True,
                "message": "Demande envoyée : à valider dans Charlemagne, puis resynchroniser EcoleDirecte."}
    finally:
        await fam.http.aclose()


# ----------------------------------------------------------------------
# Mails / téléphones des parents (« contacts »)
# ----------------------------------------------------------------------
def _nom_personne(p: dict[str, Any]) -> str:
    return f"{p.get('civilite', '')} {p.get('nomSimple') or p.get('nom', '')} {p.get('prenom', '')}".strip()


def preparer_contacts(d: dict[str, Any], modifications: dict[str, str]) -> tuple[
        dict[str, dict[str, str]], dict[str, dict[str, str]], list[str]]:
    """Valide les modifications {"responsable.telMobile": "06…", "conjoint.mailPerso": "…"}.
    → (téléphones complets à envoyer, mails remplacés, changements lisibles)."""
    if not modifications:
        raise DemandeError("Rien à demander : indiquer au moins un champ (ex. {\"responsable.telMobile\": \"06 12 34 56 78\"}).")
    tels = {b: {ch: ((d.get(b) or {}).get(ch) or "") for ch in champs} for b, champs in CHAMPS_TEL.items()}
    mails: dict[str, dict[str, str]] = {"responsable": {}, "conjoint": {}}
    changements = []
    for cle, valeur in modifications.items():
        bloc, _, champ = (cle or "").partition(".")
        if bloc not in CHAMPS_CONTACT or champ not in CHAMPS_CONTACT[bloc]:
            permis = ", ".join(f"{b}.{c}" for b, cs in CHAMPS_CONTACT.items() for c in cs)
            raise DemandeError(f"Champ « {cle} » non modifiable (champs permis : {permis}).")
        p = d.get(bloc) or {}
        if bloc == "conjoint" and not (p.get("nom") or p.get("prenom")):
            raise DemandeError("Aucun conjoint sur la fiche de cette famille : modification impossible "
                               "(le second parent a peut-être son propre compte famille).")
        v = (valeur or "").strip()
        if not v:
            raise DemandeError(f"Valeur vide pour « {cle} » : effacer une coordonnée se fait dans Charlemagne.")
        if champ.startswith("tel"):
            v, st = normaliser_telephone(v)
            if st not in ("conforme", "corrigé"):
                raise DemandeError(f"Téléphone « {valeur} » non reconnu (numéro français à 10 chiffres attendu) : "
                                   "à saisir dans Charlemagne.")
            tels[bloc][champ] = v
        else:
            v = v.lower()
            if not MAIL_OK.match(v):
                raise DemandeError(f"Adresse mail « {valeur} » invalide.")
            mails[bloc][champ] = v
        avant = p.get(champ) or ""
        if avant.strip() != v:
            changements.append(f"{_nom_personne(p)} {champ} : {avant or '(vide)'} → {v}")
    return tels, mails, changements


async def demande_contacts(admin_client, compte_id: int, modifications: dict[str, str],
                           confirm: bool = False) -> dict[str, Any]:
    _exiger_type("contacts")
    familles = await admin_client.list_utilisateurs("familles", "")
    compte = next((f for f in familles if int(f.get("id", -1)) == int(compte_id)), None)
    if not compte:
        raise DemandeError(f"Compte famille {compte_id} introuvable.")
    fam = await ouvrir_supervision(admin_client, compte)
    try:
        d = (await fam.appeler("famillecoordonnees", "get")).get("data") or {}
        tels, mails, changements = preparer_contacts(d, modifications)
        apercu = {"compte_famille": f"{compte['nom']} {compte['prenom']} (id {compte['id']})",
                  "changements": changements}
        if not changements:
            return {**apercu, "demande_envoyee": False, "message": "Déjà conforme : aucune demande nécessaire."}
        att = (await fam.appeler(f"demandemodifications/coordonnees/{compte['id']}", "get")).get("data") or {}
        if att.get("id"):
            return {**apercu, "demande_envoyee": False, "deja_en_attente": True,
                    "message": "Une demande de coordonnées est déjà en attente pour cette famille : "
                               "la faire valider dans Charlemagne d'abord."}
        if not confirm:
            return {**apercu, "demande_envoyee": False,
                    "message": "Simulation : rien n'a été envoyé. Rappeler avec confirm=True."}
        if not _demandes_actives():
            raise DemandeError("Écriture désactivée (ED_ADMIN_DEMANDES_ACTIF≠1).")
        contenu = base64.b64encode(xml_coordonnees(d, tels, mails).encode("utf-8")).decode()
        r = await fam.appeler("demandemodifications/coordonnees", "post", {"modifications": {"contenu": contenu}})
        _journaliser({"horodatage": datetime.now().isoformat(timespec="seconds"), "type": "contacts",
                      "id_eleve": "", "eleve": "", "id_compte_famille": compte["id"],
                      "changements": " ; ".join(changements), "corps": "(XML complet, mails/téléphones demandés)",
                      "code_api": r.get("code")})
        if r.get("code") != 200:
            raise DemandeError(f"Demande refusée (code {r.get('code')} — {r.get('message') or ''}).")
        return {**apercu, "demande_envoyee": True,
                "message": "Demande envoyée : à valider dans Charlemagne, puis resynchroniser EcoleDirecte."}
    finally:
        await fam.http.aclose()
