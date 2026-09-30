"""Garde-fous des demandes de modification (demandes.py) et des ajouts au dépôt
(compte choisi, listes par numéro, état des pièces) — sans réseau."""
from __future__ import annotations

import base64

import pytest

from ecoledirecte_admin_mcp import demandes as dm
from ecoledirecte_admin_mcp import depot_pieces as dp

ELEVE_ED = {"id": 5, "idEtablissement": 1, "prenom": "Alice", "idRegime": 1,
            "activites": [{"code": "ETUDE", "jour1": True, "jour2": True},
                          {"code": "MIDI", "type": "Repas", "jour1": True, "jour2": True, "jour4": True, "jour5": True}]}
FICHE = {"adresseLigne1": "1 rue des Tests", "codePostal": "77000", "ville": "TESTVILLE",
         "situationFamiliale": {"code": 2}, "eleves": [ELEVE_ED],
         "responsable": {"nom": "DUPONT", "prenom": "Jean", "mailPerso": "j@example.org", "telMobile": "0612345678",
                         "telTravail": "+33 1 23 45 67 89", "telDomicile": "06 11 22 33 44", "profession": "Testeur"},
         "conjoint": {"nom": "DUPONT", "prenom": "Anne", "telMobile": "+966 55 123 4567", "telTravail": ""}}
COMPTES = [{"id": 10, "nom": "DUPONT", "prenom": "Jean", "type": "responsable"},
           {"id": 11, "nom": "DUPONT", "prenom": "Anne", "type": "conjoint"}]


class FakeHttp:
    async def aclose(self):
        pass


class FakeFam:
    def __init__(self, en_attente=None):
        self.appels, self.http, self.en_attente = [], FakeHttp(), en_attente or {}

    async def appeler(self, chemin, verbe, data=None):
        self.appels.append((chemin, verbe, data))
        if chemin == "famillecoordonnees":
            return {"code": 200, "data": FICHE}
        if chemin.startswith("demandemodifications/coordonnees/"):
            return {"code": 200, "data": self.en_attente}
        return {"code": 200}

    def posts(self):
        return [a for a in self.appels if a[1] == "post"]


class FakeAdmin:
    async def list_utilisateurs(self, t, f):
        return COMPTES


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ED_ADMIN_DEMANDES_ACTIF", raising=False)
    monkeypatch.delenv("ED_ADMIN_DEMANDES_TYPES", raising=False)
    monkeypatch.delenv("ED_ADMIN_DEMANDES_ACTIVITES", raising=False)
    monkeypatch.setattr(dm, "JOURNAL", tmp_path / "demandes.csv")

    async def resoudre(admin, id_eleve, *a):
        return {"eleve": {"id": id_eleve, "nom": "DUPONT", "prenom": "Alice", "libelleClasse": "CP"},
                "comptes": COMPTES, "compte": COMPTES[0]}
    monkeypatch.setattr(dm, "resoudre_eleve_famille", resoudre)
    fam = {"f": FakeFam()}

    async def superviser(admin, compte):
        fam["compte"] = compte
        return fam["f"]
    monkeypatch.setattr(dm, "ouvrir_supervision", superviser)
    return fam


# --- fonctions pures ------------------------------------------------------
def test_jours():
    assert dm.normaliser_jours("vjl") == "LJV"
    assert dm.normaliser_jours("") == ""
    with pytest.raises(dm.DemandeError):
        dm.normaliser_jours("LX")


def test_modif_seulement_ce_qui_change():
    modif, ch = dm.construire_modif_eleve(ELEVE_ED, {"ETUDE": "LM", "MIDI": "LJ"}, None)
    assert [a["code"] for a in modif["activites"]] == ["MIDI"]
    midi = modif["activites"][0]
    assert midi["type"] == "Repas" and midi["jour1"] and midi["jour4"] and not midi["jour2"]
    assert "idRegime" not in modif and ch == ["MIDI : LMJV → LJ"]


def test_deja_conforme():
    assert dm.construire_modif_eleve(ELEVE_ED, {"ETUDE": "LM"}, 1) == (None, [])


def test_activite_inconnue_refusee(monkeypatch):
    with pytest.raises(dm.DemandeError, match="inconnue"):
        dm.construire_modif_eleve(ELEVE_ED, {"PISCINE": "L"}, None)
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIVITES", "PISCINE|ANGLAIS")
    modif, _ = dm.construire_modif_eleve(ELEVE_ED, {"piscine": "L"}, None)
    assert modif["activites"][0]["code"] == "PISCINE"


def test_regime():
    modif, ch = dm.construire_modif_eleve(ELEVE_ED, None, 2)
    assert modif["idRegime"] == 2 and modif["activites"] == []


@pytest.mark.parametrize("v,attendu", [("0612345678", ("06 12 34 56 78", "corrigé")),
                                       ("+33 1 23 45 67 89", ("01 23 45 67 89", "corrigé")),
                                       ("06 11 22 33 44", ("06 11 22 33 44", "conforme")),
                                       ("+966 55 123 4567", ("+966 55 123 4567", "exception")),
                                       ("06 12 34 56 78 / 07 11 22 33 44", ("06 12 34 56 78 / 07 11 22 33 44", "exception")),
                                       ("", ("", "vide"))])
def test_telephones(v, attendu):
    assert dm.normaliser_telephone(v) == attendu


def test_xml_ne_change_que_les_telephones():
    tels, lignes = dm.analyser_telephones(FICHE)
    xml = dm.xml_coordonnees(FICHE, tels)
    assert "<responsableTelMobile>06 12 34 56 78</responsableTelMobile>" in xml
    assert "<conjointTelMobile>+966 55 123 4567</conjointTelMobile>" in xml   # exception : inchangé
    assert "<adresse1>1 rue des Tests</adresse1>" in xml and "<responsableProfession>Testeur</responsableProfession>" in xml
    assert "<situationFamiliale>2</situationFamiliale>" in xml
    assert {l["statut"] for l in lignes} == {"corrigé", "exception"}


# --- garde-fous des demandes ----------------------------------------------
async def test_simulation_n_envoie_rien(env):
    r = await dm.demande_activites(FakeAdmin(), 5, {"MIDI": "LJ"})
    assert r["demande_envoyee"] is False and r["changements"] == ["MIDI : LMJV → LJ"]
    assert env["f"].posts() == []


async def test_ecriture_desactivee_par_defaut(env):
    with pytest.raises(dm.DemandeError, match="désactivée"):
        await dm.demande_activites(FakeAdmin(), 5, {"MIDI": "LJ"}, confirm=True)
    assert env["f"].posts() == []


async def test_envoi_et_journal(env, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIF", "1")
    r = await dm.demande_activites(FakeAdmin(), 5, {"MIDI": "LJ"}, regime=2, confirm=True)
    assert r["demande_envoyee"] is True
    (chemin, verbe, data), = env["f"].posts()
    assert chemin == "demandemodifications/eleve" and data["modifications"]["idRegime"] == 2
    assert dm.JOURNAL.exists()


async def test_demande_deja_en_attente(env, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIF", "1")
    env["f"] = FakeFam(en_attente={"eleves": [{"idEleve": 5}]})
    r = await dm.demande_activites(FakeAdmin(), 5, {"MIDI": "LJ"}, confirm=True)
    assert r["deja_en_attente"] is True and env["f"].posts() == []


async def test_type_non_autorise(env, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_DEMANDES_TYPES", "activites")
    with pytest.raises(dm.DemandeError, match="non autorisé"):
        await dm.demande_activites(FakeAdmin(), 5, None, regime=2)
    with pytest.raises(dm.DemandeError, match="non autorisé"):
        await dm.demande_telephones(FakeAdmin(), 10)


async def test_telephones_simulation_puis_envoi(env, monkeypatch):
    r = await dm.demande_telephones(FakeAdmin(), 10)
    assert r["demande_envoyee"] is False and len(r["corrections"]) == 2 and len(r["a_traiter_a_la_main"]) == 1
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIF", "1")
    r = await dm.demande_telephones(FakeAdmin(), 10, confirm=True)
    (chemin, _, data), = env["f"].posts()
    assert chemin == "demandemodifications/coordonnees"
    assert "06 12 34 56 78" in base64.b64decode(data["modifications"]["contenu"]).decode()


async def test_telephones_demande_en_attente(env, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIF", "1")
    env["f"] = FakeFam(en_attente={"id": 99})
    r = await dm.demande_telephones(FakeAdmin(), 10, confirm=True)
    assert r["deja_en_attente"] is True and env["f"].posts() == []


async def test_aucune_fonction_bancaire():
    assert not [n for n in dir(dm) if any(k in n.lower() for k in ("iban", "bic", "reglement", "banque"))]


# --- ajouts au dépôt -------------------------------------------------------
def test_compte_choisi_doit_etre_rattache():
    res = {"comptes": COMPTES, "compte": COMPTES[0]}
    assert dp.choisir_compte(res, None)["id"] == 10
    assert dp.choisir_compte(res, 11)["id"] == 11
    with pytest.raises(dp.DepotError, match="pas rattaché"):
        dp.choisir_compte(res, 999)


def test_liste_autorisee_par_numero(monkeypatch):
    monkeypatch.setenv("ED_ADMIN_DEPOT_LISTES", "Fiches Rentrée|7")
    assert dp._liste_autorisee({"id": 7, "libelle": "Attestations Assurance"})
    assert dp._liste_autorisee({"id": 1, "libelle": "Fiches Rentrée"})
    assert not dp._liste_autorisee({"id": 8, "libelle": "Autre"})
    assert not dp._liste_autorisee({"id": 17, "libelle": "Autre"})


# --- mails / téléphones des parents (contacts) -----------------------------
def test_contacts_ne_change_que_les_champs_demandes():
    tels, mails, ch = dm.preparer_contacts(FICHE, {"responsable.telMobile": "07.11.22.33.44",
                                                   "conjoint.mailPerso": " Anne.Dupont@Example.org "})
    xml = dm.xml_coordonnees(FICHE, tels, mails)
    assert "<responsableTelMobile>07 11 22 33 44</responsableTelMobile>" in xml
    assert "<conjointMailPerso>anne.dupont@example.org</conjointMailPerso>" in xml
    # le reste est recopié tel quel, y compris les numéros non conformes
    assert "<responsableTelTravail>+33 1 23 45 67 89</responsableTelTravail>" in xml
    assert "<conjointTelMobile>+966 55 123 4567</conjointTelMobile>" in xml
    assert "<responsableMailPerso>j@example.org</responsableMailPerso>" in xml
    assert "<adresse1>1 rue des Tests</adresse1>" in xml
    assert len(ch) == 2


@pytest.mark.parametrize("modifs,message", [
    ({"responsable.adresse1": "x"}, "non modifiable"),
    ({"responsable.iban": "x"}, "non modifiable"),
    ({"conjoint.telDomicile": "0611223344"}, "non modifiable"),
    ({"responsable.telMobile": "+966 55 123 4567"}, "non reconnu"),
    ({"responsable.mailPerso": "pas-un-mail"}, "invalide"),
    ({"responsable.mailPerso": ""}, "vide"),
    ({}, "Rien à demander"),
])
def test_contacts_refus(modifs, message):
    with pytest.raises(dm.DemandeError, match=message):
        dm.preparer_contacts(FICHE, modifs)


def test_contacts_sans_conjoint():
    fiche = {**FICHE, "conjoint": {}}
    with pytest.raises(dm.DemandeError, match="Aucun conjoint"):
        dm.preparer_contacts(fiche, {"conjoint.telMobile": "0611223344"})


def test_contacts_deja_conforme():
    _, _, ch = dm.preparer_contacts(FICHE, {"responsable.telDomicile": "0611223344"})
    assert ch == []


async def test_contacts_simulation_puis_envoi(env, monkeypatch):
    r = await dm.demande_contacts(FakeAdmin(), 10, {"responsable.mailTravail": "jean@example.org"})
    assert r["demande_envoyee"] is False and env["f"].posts() == []
    with pytest.raises(dm.DemandeError, match="désactivée"):
        await dm.demande_contacts(FakeAdmin(), 10, {"responsable.mailTravail": "jean@example.org"}, confirm=True)
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIF", "1")
    r = await dm.demande_contacts(FakeAdmin(), 10, {"responsable.mailTravail": "jean@example.org"}, confirm=True)
    assert r["demande_envoyee"] is True
    (chemin, _, data), = env["f"].posts()
    assert chemin == "demandemodifications/coordonnees"
    assert "<responsableMailTravail>jean@example.org</responsableMailTravail>" in \
        base64.b64decode(data["modifications"]["contenu"]).decode()
    assert dm.JOURNAL.exists()


async def test_contacts_en_attente_et_type(env, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_DEMANDES_ACTIF", "1")
    env["f"] = FakeFam(en_attente={"id": 99})
    r = await dm.demande_contacts(FakeAdmin(), 10, {"responsable.telMobile": "0711223344"}, confirm=True)
    assert r["deja_en_attente"] is True and env["f"].posts() == []
    monkeypatch.setenv("ED_ADMIN_DEMANDES_TYPES", "activites,telephones")
    with pytest.raises(dm.DemandeError, match="non autorisé"):
        await dm.demande_contacts(FakeAdmin(), 10, {"responsable.telMobile": "0711223344"})
