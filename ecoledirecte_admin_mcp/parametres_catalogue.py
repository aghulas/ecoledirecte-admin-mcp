"""Catalogue des paramètres établissement de la console admin EcoleDirecte.

Pourquoi : `GET parametres` renvoie « 0 » (sans erreur) pour un libellé qui
n'existe pas — une faute de frappe ou un accent manquant (« Sites/Eleves/Actif »
au lieu de « Sites/Elèves/Actif ») donne donc une réponse plausible mais fausse.
Le catalogue (data/parametres_front.json, régénéré par
tools/extraire_parametres.py à partir du JavaScript public du front admin)
permet de refuser les libellés inconnus, de proposer le bon, et de lire un menu
entier de l'admin d'un coup, avec des intitulés lisibles rangés comme dans le
support de formation Aplim (Paramétrages généraux / familles / élèves /
professeurs / personnels / entreprises).

Les indices d'établissement sont ramenés à 0 (`Etablissement_0`), l'indice
utilisé par le front quand le « paramétrage par établissement » est désactivé.
"""
from __future__ import annotations

import difflib
import functools
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

_DATA = Path(__file__).with_name("data") / "parametres_front.json"

MENU_GENERAUX = "Paramétrages généraux"
MENUS = (MENU_GENERAUX, "Paramétrages familles", "Paramétrages élèves",
         "Paramétrages professeurs", "Paramétrages personnels", "Paramétrages entreprises")

# Contrôleur du front → rubrique des Paramétrages généraux (menu de gauche de l'admin).
_RUBRIQUES_GENERALES = {
    "AccesSitesCtrl": "Accès sites",
    "PageContactCtrl": "Page contact",
    "MotspasseUtilisateursCtrl": "Mot de passe utilisateurs",
    "AlertesTransfertsCtrl": "Alertes transferts",
    "AgendaCtrl": "Agenda / Post-it",
    "MessagerieCtrl": "Messagerie",
    "DocumentsCtrl": "Documents",
    "QuestionnairesCtrl": "Formulaires",
    "ModeRestreintCtrl": "Mode restreint",
    "ManuelsScolairesCtrl": "Manuels scolaires",
    "ConnecteurDetailDirectiveCtrl": "Connecteurs (Mes applis)",
    "OuiPassCtrl": "OuiPass",
    "PackIACtrl": "Pack IA",
    "EntCtrl": "ENT",
    "EntAdministrationCtrl": "ENT",
    "ReglementsEnLigneCtrl": "Règlements en ligne",
    "SitePreinscriptionsCtrl": "Pré-inscriptions",
}

# Début du nom de contrôleur → rubrique des menus par profil.
_RUBRIQUES_PROFIL = (
    ("Viescolaire", "Vie scolaire"), ("JournalClasse", "Journal de classe"),
    ("CahierJournal", "Cahier journal"), ("Cdt", "Cahier de textes"),
    ("Administratif", "Administratif"), ("Comptabilite", "Comptabilité"),
    ("Finances", "Comptabilité"), ("NotesPeriodes", "Notes"), ("Notes", "Notes"),
    ("Moyennes", "Moyennes"), ("Appreciations", "Appréciations"), ("LSUN", "LSU"),
    ("LSL", "LSL"), ("CarnetCorrespondance", "Carnet de correspondance"),
    ("Edt", "Emploi du temps"), ("SuiviStage", "Stages"), ("Badge", "Badge"),
    ("Emargement", "Émargement"), ("LivretApprentissage", "Livret d'apprentissage"),
    ("Appel", "Feuille d'appel"), ("SuiviComportement", "Suivi du comportement"),
    ("Montessori", "Montessori"),
)

_MENU_PAR_PREFIXE = (
    ("sites/familles/", "Paramétrages familles"),
    ("sites/eleves/", "Paramétrages élèves"),
    ("sites/professeurs/", "Paramétrages professeurs"),
    ("sites/personnels/", "Paramétrages personnels"),
    ("sites/entreprises/", "Paramétrages entreprises"),
)
_MENU_PAR_CONTROLEUR = (
    ("Famille", "Paramétrages familles"), ("Eleve", "Paramétrages élèves"),
    ("Professeur", "Paramétrages professeurs"), ("Personnel", "Paramétrages personnels"),
    ("Entreprise", "Paramétrages entreprises"),
)

# Intitulés tels qu'affichés dans l'admin (ou dans le support Aplim) pour les
# réglages les plus courants. Les autres reçoivent un intitulé calculé.
INTITULES: dict[str, str] = {
    "Sites/Familles/Actif": "Accès au site Familles",
    "Sites/Elèves/Actif": "Accès au site Élèves",
    "Sites/Professeurs/Actif": "Accès au site Professeurs",
    "Sites/Personnels/Actif": "Accès au site Personnels",
    "Sites/Entreprises/Actif": "Accès au site Entreprises (Charlemagne Entreprise requis)",
    "Sites/Inscriptions/Actif": "Site Pré-inscriptions",
    "Sites/CharteUtilisation/Actif": "Activer la charte d'utilisation",
    "Sites/CharteUtilisation/Contenu": "Contenu de la charte d'utilisation",
    "Sites/Paramétrage/AssociationComptes": "Autoriser l'association de comptes EcoleDirecte",
    "Sites/Paramétrage/ConjointsAutorisés": "Comptes conjoints autorisés",
    "Sites/Paramétrage/ParamétrageParEtablissement": "Paramétrage par établissement (irréversible)",
    "Sites/FuseauHoraire": "Fuseau horaire de l'établissement",
    "Sites/DateFinModeEte": "Date de fin du mode été — familles/élèves (MMJJ)",
    "Sites/DateFinModeEteProf": "Date de fin du mode été — enseignants (MMJJ)",
    "Sites/Paramétrage/NombrePostit": "Nombre de post-it affichés (page d'accueil)",
    "Sites/Paramétrage/NombreAgenda": "Nombre d'événements d'agenda affichés (page d'accueil)",
    "Sites/Agenda/Etablissement_0/Couleur": "Couleur des événements de l'établissement",
    "Sites/NiveauMDPAutorisé": "Niveau de sécurité des mots de passe (1 faible, 2 normal, 3 fort)",
    "Sites/ValiditeMDP/Actif": "Expiration des mots de passe",
    "Sites/ValiditeMDP/NbJours": "Durée de validité des mots de passe (jours)",
    "Sites/BlocageCompte/NbTentativesMaxAtteinte/Actif": "Bloquer le compte après 10 tentatives ratées",
    "Sites/Notification/Connexion/Actif": "Connexion inhabituelle : notifier professeurs et personnels",
    "Sites/Notification/Connexion/Auth2FactorFE/Actif": "Connexion inhabituelle : question aléatoire familles/élèves (2e facteur)",
    "Administrateur/Alertes/Warnings/Email": "Alerte « messages importants » par e-mail",
    "Administrateur/Alertes/Warnings/SMS": "Alerte « messages importants » par SMS",
    "Administrateur/Alertes/Erreurs/Email": "Alerte « erreurs de transfert » par e-mail",
    "Administrateur/Alertes/Erreurs/SMS": "Alerte « erreurs de transfert » par SMS",
    "Administrateur/Alertes/Transferts/Email": "Alerte « transferts depuis Charlemagne Outils » par e-mail",
    "Administrateur/Alertes/Transferts/SMS": "Alerte « transferts depuis Charlemagne Outils » par SMS",
    "Autorisations/SMS": "SMS activés pour l'établissement",
    "Messagerie/Actif": "Activer la messagerie",
    "Messagerie/Etablissement_0/ParentsMessagesEnfants": "Les parents peuvent lire les messages de leurs enfants",
    "Messagerie/Etablissement_0/NotificationEmail": "Notification par e-mail des nouveaux messages",
    "Messagerie/Etablissement_0/NotificationEmailAvecContenu": "Inclure le contenu du message dans la notification",
    "Messagerie/Etablissement_0/NomENT/FamillesEleves": "Nom du site dans les notifications — familles/élèves",
    "Messagerie/Etablissement_0/URLENT/FamillesEleves": "URL du site dans les notifications — familles/élèves (ne pas modifier)",
    "Messagerie/Etablissement_0/NomENT/Professeurs": "Nom du site dans les notifications — professeurs/personnels",
    "Messagerie/Etablissement_0/URLENT/Professeurs": "URL du site dans les notifications — professeurs/personnels (ne pas modifier)",
    "Messagerie/Etablissement_0/BlackListProf": "Activer la liste rouge enseignant",
    "Messagerie/Etablissement_0/RechercheParClasse/Professeurs": "Recherche sur l'ensemble des classes (enseignants)",
    "Sites/Familles/Documents/Etablissement_0/Administratifs": "Afficher les documents « Administratifs »",
    "Sites/Familles/Documents/Etablissement_0/Notes": "Afficher les documents « Notes » (bulletins)",
    "Sites/Familles/Documents/Etablissement_0/VS": "Afficher les documents « Vie scolaire »",
    "Sites/Familles/Documents/Etablissement_0/Entreprise": "Afficher les documents « Entreprise »",
    "Sites/Familles/Documents/Etablissement_0/InsReins": "Afficher les documents « Inscription / Réinscription »",
    "Sites/Familles/Documents/Etablissement_0/Factures": "Afficher les factures",
    "Sites/Familles/Documents/Etablissement_0/NotificationEmail": "Notification par e-mail d'un nouveau document",
    "Sites/Familles/Coordonnees/Actif": "Permettre les demandes de modification de coordonnées",
    "Sites/Familles/Coordonnees/Aide": "Aide aux familles — modification d'informations personnelles",
    "Sites/Familles/ModificationsRentreeEleve/Actif": "Permettre les demandes de modification élève (rentrée)",
    "Sites/Familles/ModificationsRentreeEleve/Aide": "Aide aux familles — modification d'informations élèves",
    "Sites/Familles/Comptabilité/Actif": "Afficher la situation de compte",
    "Sites/Familles/Comptabilité/PortesMonaie/Actif": "Afficher les porte-monnaie",
    "Sites/Familles/Comptabilité/RèglementsEnLigne/Actif": "Règlement en ligne",
    "Sites/Familles/PageDeGarde/Etablissement_0/NomEtablissement": "Page contact — nom de l'établissement",
    "Sites/Familles/PageDeGarde/Etablissement_0/Adresse": "Page contact — adresse (base64)",
    "Sites/Familles/PageDeGarde/Etablissement_0/Email": "Page contact — e-mail",
    "Sites/Familles/PageDeGarde/Etablissement_0/Contact": "Page contact — personne contact",
    "Sites/Familles/PageDeGarde/Etablissement_0/Téléphone": "Page contact — téléphone",
    "Sites/Familles/PageDeGarde/Etablissement_0/Site": "Page contact — site internet",
    "Sites/Familles/PageDeGarde/Etablissement_0/Présentation": "Page contact — texte de présentation (base64)",
    "Sites/Familles/PageDeGarde/Etablissement_0/Logo": "Page contact — logo",
    "Sites/Professeurs/CahierJournal/Actif": "Permettre la saisie du cahier journal",
    "Sites/Professeurs/CahierDeTextePrimaire/Actif": "Permettre la saisie du cahier de textes primaire",
    "Sites/Professeurs/CahierDeTextePrimaire/SaisieSimplifiee": "Saisie simplifiée (affichage en semaine)",
    "Sites/Professeurs/CahierDeTexte/Archives": "Consulter les archives du cahier de textes",
    "Sites/Professeurs/CahierDeTexte/GestionCorrespondances": "Correspondances emploi du temps / notes (à laisser désactivé)",
    "Sites/Professeurs/CoordonneesFamille/Actif": "Consultation des classes : coordonnées des responsables",
    "Sites/Professeurs/Consultation/CoordonneesEnseignant/Actif": "Annuaire : coordonnées des enseignants",
    "Sites/Professeurs/Consultation/EmploiDuTempsEnseignant/Actif": "Annuaire : emploi du temps des enseignants",
    "Sites/Professeurs/Dispositifs/Actif": "Visualisation des dispositifs des élèves",
    "Sites/Professeurs/RDVPP/Actif": "Prise de rendez-vous familles (enseignants)",
    "Sites/Personnels/RDVPP/Actif": "Prise de rendez-vous familles (personnels)",
    "Sites/Admin/3DSecure/Actif": "3DSecure sur la console admin",
}

_PROFILS_MESSAGERIE = {"Prof": "Professeurs", "Fam": "Familles", "Elv": "Élèves",
                       "Admin": "Administratifs", "EspTravail": "Espaces de travail",
                       "Entreprise": "Tuteurs entreprise"}
_FLUX_RE = re.compile(r"^(?:ModeRestreint/)?Messagerie/Etablissement_0/([A-Za-z]+)-([A-Za-z]+)$")
_ETAB_RE = re.compile(r"Etablissement_\d+")


def _sans_accents(texte: str) -> str:
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()


def normaliser(libelle: str) -> str:
    """Ramène tout indice d'établissement à 0 (forme du catalogue)."""
    return _ETAB_RE.sub("Etablissement_0", (libelle or "").strip())


@functools.lru_cache(maxsize=1)
def _donnees() -> dict[str, Any]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _motifs() -> list[tuple[re.Pattern[str], str]]:
    out = []
    for m in _donnees().get("motifs", []):
        brut = m["motif"]
        regex = "^" + re.sub(r"\\\{\w+\\\}", r"[^/]+", re.escape(brut)) + "$"
        out.append((re.compile(regex), brut))
    return out


@functools.lru_cache(maxsize=1)
def _index_sans_accents() -> dict[str, str]:
    return {_sans_accents(k): k for k in _donnees()["libelles"]}


def info_source() -> dict[str, Any]:
    d = _donnees()
    return {"source": d.get("source"), "date_extraction": d.get("date_extraction"),
            "nb_libelles": len(d["libelles"]), "nb_motifs": len(d.get("motifs", []))}


def motif_de(libelle: str) -> str | None:
    norm = normaliser(libelle)
    for regex, brut in _motifs():
        if regex.match(norm):
            return brut
    return None


def est_connu(libelle: str) -> bool:
    norm = normaliser(libelle)
    return norm in _donnees()["libelles"] or motif_de(norm) is not None


def suggestions(libelle: str, n: int = 5) -> list[str]:
    """Libellés du catalogue les plus proches (accents et casse d'abord)."""
    norm = normaliser(libelle)
    exact = _index_sans_accents().get(_sans_accents(norm))
    proches = difflib.get_close_matches(norm, list(_donnees()["libelles"]), n=n, cutoff=0.6)
    out = ([exact] if exact else []) + [p for p in proches if p != exact]
    return out[:n]


def _menu(libelle: str, controleurs: list[str]) -> str:
    if any(c in _RUBRIQUES_GENERALES for c in controleurs):
        return MENU_GENERAUX
    bas = _sans_accents(libelle)
    for prefixe, menu in _MENU_PAR_PREFIXE:
        if bas.startswith(prefixe):
            return menu
    for morceau, menu in _MENU_PAR_CONTROLEUR:
        if any(morceau in c for c in controleurs):
            return menu
    return MENU_GENERAUX


def _rubrique(controleurs: list[str]) -> str:
    for c in controleurs:
        if c in _RUBRIQUES_GENERALES:
            return _RUBRIQUES_GENERALES[c]
    for c in controleurs:
        for debut, rubrique in _RUBRIQUES_PROFIL:
            if c.startswith(debut):
                return rubrique
    return "Autres"


def intitule(libelle: str) -> str:
    norm = normaliser(libelle)
    if norm in INTITULES:
        return INTITULES[norm]
    m = _FLUX_RE.match(norm)
    if m and m.group(1) in _PROFILS_MESSAGERIE and m.group(2) in _PROFILS_MESSAGERIE:
        prefixe = "Mode restreint — messagerie" if norm.startswith("ModeRestreint/") else "Messagerie"
        return f"{prefixe} : {_PROFILS_MESSAGERIE[m.group(1)]} → {_PROFILS_MESSAGERIE[m.group(2)]}"
    morceaux = [p for p in norm.split("/") if p not in ("Sites", "Etablissement_0", "Actif")]
    texte = " › ".join(morceaux) or norm
    return texte + (" (activé ?)" if norm.endswith("/Actif") else "")


def entree(libelle: str) -> dict[str, Any] | None:
    """Fiche catalogue d'un libellé (None s'il est inconnu)."""
    from .client import is_front_excluded_param, is_secret_param  # import tardif (évite un cycle)

    norm = normaliser(libelle)
    brut = _donnees()["libelles"].get(norm)
    motif = None if brut else motif_de(norm)
    if brut is None and motif is None:
        return None
    controleurs = brut["controleurs"] if brut else next(
        m["controleurs"] for m in _donnees()["motifs"] if m["motif"] == motif)
    fiche = {
        "libelle": libelle if libelle == norm else norm,
        "intitule": intitule(norm),
        "menu": _menu(norm, controleurs),
        "rubrique": _rubrique(controleurs),
        "certain": bool(brut and brut["certain"]),
        "secret": is_secret_param(norm),
        "modifiable": not (is_secret_param(norm) or is_front_excluded_param(norm)),
    }
    if brut and brut.get("base64"):
        fiche["base64"] = True
    if motif:
        fiche["motif"] = motif
    return fiche


def lister(menu: str | None = None, rubrique: str | None = None,
           recherche: str | None = None) -> list[dict[str, Any]]:
    """Entrées du catalogue filtrées (menu / rubrique : début ou nom exact,
    sans accents ni casse ; recherche : dans le libellé ou l'intitulé)."""
    def correspond(valeur: str, filtre: str | None) -> bool:
        if not filtre:
            return True
        v, f = _sans_accents(valeur), _sans_accents(filtre).strip()
        return v == f or v.startswith(f) or v.replace("parametrages ", "").startswith(f)

    out = []
    for lib in _donnees()["libelles"]:
        e = entree(lib)
        if not e or not correspond(e["menu"], menu) or not correspond(e["rubrique"], rubrique):
            continue
        if recherche:
            r = _sans_accents(recherche)
            if r not in _sans_accents(lib) and r not in _sans_accents(e["intitule"]):
                continue
        out.append(e)
    return out


def sommaire() -> dict[str, dict[str, int]]:
    """Nombre de libellés par menu puis rubrique."""
    out: dict[str, dict[str, int]] = {m: {} for m in MENUS}
    for e in lister():
        out.setdefault(e["menu"], {})
        out[e["menu"]][e["rubrique"]] = out[e["menu"]].get(e["rubrique"], 0) + 1
    return {m: dict(sorted(r.items())) for m, r in out.items() if r}


def decoder_base64(valeur: str) -> str | None:
    """Décode une valeur stockée en base64 par le front (adresse, présentation…)."""
    import base64
    import binascii

    try:
        # Le serveur peut renvoyer un base64 « MIME » coupé en lignes de 76 caractères.
        return base64.b64decode("".join(valeur.split()), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def encoder_base64(texte: str) -> str:
    import base64

    return base64.b64encode(texte.encode("utf-8")).decode("ascii")
