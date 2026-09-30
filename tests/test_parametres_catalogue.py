"""Catalogue des paramètres (data/parametres_front.json) : libellés connus,
suggestions, intitulés, menus, base64, et garde-fous associés (lecture refusée
hors catalogue, écriture refusée hors catalogue avant tout appel réseau)."""
from __future__ import annotations

import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from ecoledirecte_admin_mcp import parametres_catalogue as cat
from ecoledirecte_admin_mcp import server
from ecoledirecte_admin_mcp.client import EcoleDirecteAdminClient, ForbiddenEndpointError

from ._helpers import API, decode_body, fake_auth, ok


def test_catalogue_charge_et_volumineux():
    info = cat.info_source()
    assert info["nb_libelles"] > 500
    assert info["nb_motifs"] > 10


@pytest.mark.parametrize("libelle", [
    "Sites/Familles/Actif", "Sites/Elèves/Actif", "Sites/Professeurs/Actif",
    "Messagerie/Etablissement_0/Fam-Admin", "Sites/Familles/Documents/Etablissement_0/Administratifs",
    "Sites/Notification/Connexion/Auth2FactorFE/Actif", "Sites/DateFinModeEte",
    "Sites/Familles/PageDeGarde/Etablissement_0/Email",
])
def test_libelles_reels_connus(libelle):
    assert cat.est_connu(libelle)


def test_libelle_inconnu_et_suggestion_accent():
    assert not cat.est_connu("Zzz/Inexistant/Actif")
    assert not cat.est_connu("Sites/Enseignants/Actif")
    assert cat.suggestions("Sites/Eleves/Actif")[0] == "Sites/Elèves/Actif"


def test_indice_etablissement_normalise():
    assert cat.est_connu("Messagerie/Etablissement_3/Fam-Admin")
    assert cat.entree("Messagerie/Etablissement_3/Fam-Admin")["libelle"] == "Messagerie/Etablissement_0/Fam-Admin"


def test_motif_dynamique():
    e = cat.entree("ModeRestreint/PeriodesModeNormal_Lundi_de")
    assert e and e["motif"] == "ModeRestreint/PeriodesModeNormal_{jour}_de" and not e["certain"]


def test_intitules_et_rangement():
    e = cat.entree("Messagerie/Etablissement_0/Fam-Admin")
    assert e["intitule"] == "Messagerie : Familles → Administratifs"
    assert (e["menu"], e["rubrique"]) == ("Paramétrages généraux", "Messagerie")
    assert cat.entree("Sites/Entreprises/Actif")["rubrique"] == "Accès sites"
    doc = cat.entree("Sites/Familles/Documents/Etablissement_0/Administratifs")
    assert doc["rubrique"] == "Documents" and doc["intitule"].startswith("Afficher")


def test_sensibles_marques():
    assert cat.entree("Sites/MDPPerduSMS")["secret"]
    assert not cat.entree("Sites/ValiditeMDP/NbJours")["modifiable"]
    assert cat.entree("Sites/Familles/Actif")["modifiable"]


def test_lister_par_menu_rubrique_recherche():
    messagerie = cat.lister("généraux", "messagerie")
    assert len(messagerie) >= 20 and all(e["rubrique"] == "Messagerie" for e in messagerie)
    assert cat.lister("familles", "documents") == [] or all(e["menu"] == "Paramétrages familles" for e in cat.lister("familles", "documents"))
    assert any(e["libelle"] == "Sites/DateFinModeEte" for e in cat.lister(recherche="mode ete"))
    assert "Paramétrages généraux" in cat.sommaire()


def test_base64():
    assert cat.entree("Sites/Familles/PageDeGarde/Etablissement_0/Adresse").get("base64")
    enc = cat.encoder_base64("71 rue X\n77300 Fontainebleau")
    assert cat.decoder_base64(enc) == "71 rue X\n77300 Fontainebleau"
    assert cat.decoder_base64("pas du base64 !") is None


# ---- outil de lecture : refus hors catalogue, sans appel réseau ----
async def test_parametres_get_refuse_libelle_inconnu(monkeypatch):
    appele = False

    class Faux:
        async def get_parametres(self, libelles):
            nonlocal appele
            appele = True
            return []

    monkeypatch.setattr(server, "_client", Faux())
    with pytest.raises(ToolError, match="Sites/Elèves/Actif"):
        await server.ed_admin_parametres_get(["Sites/Eleves/Actif"])
    assert not appele


async def test_parametres_get_enrichit_et_decode(monkeypatch):
    adresse = cat.encoder_base64("71 rue St Honoré")

    class Faux:
        async def get_parametres(self, libelles):
            return [{"libelle": "Sites/Familles/PageDeGarde/Etablissement_0/Adresse", "valeur": adresse, "encoded": False}]

    monkeypatch.setattr(server, "_client", Faux())
    res = await server.ed_admin_parametres_get(["Sites/Familles/PageDeGarde/Etablissement_0/Adresse"])
    assert res[0]["valeur_decodee"] == "71 rue St Honoré"
    assert res[0]["rubrique"] == "Page contact"


async def test_parametres_get_hors_catalogue_signale(monkeypatch):
    class Faux:
        async def get_parametres(self, libelles):
            return [{"libelle": "Zzz/X", "valeur": "0", "encoded": False}]

    monkeypatch.setattr(server, "_client", Faux())
    res = await server.ed_admin_parametres_get(["Zzz/X"], hors_catalogue=True)
    assert res[0]["hors_catalogue"] is True


async def test_parametrage_lire_par_lots(monkeypatch):
    lots = []

    class Faux:
        async def get_parametres(self, libelles):
            lots.append(len(libelles))
            return [{"libelle": l, "valeur": "1", "encoded": False} for l in libelles]

    monkeypatch.setattr(server, "_client", Faux())
    res = await server.ed_admin_parametrage_lire("généraux", "messagerie")
    assert res["nombre"] == sum(lots) and all(n <= 100 for n in lots)
    assert "Paramétrages généraux › Messagerie" in res["rubriques"]


# ---- écriture : refus hors catalogue avant tout réseau ; base64 encodé ----
@respx.mock
async def test_set_parametre_refuse_libelle_inconnu(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp")
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(ForbiddenEndpointError, match="Sites/Elèves/Actif"):
        await client.set_parametre("Sites/Eleves/Actif", "1", confirm=True)
    assert not route.calls
    await client.aclose()


@respx.mock
async def test_set_parametre_base64_encode(tmp_path):
    lib = "Sites/Familles/PageDeGarde/Etablissement_0/Présentation"
    nouveau = cat.encoder_base64("Bienvenue")
    reponses = iter([
        ok({"parametres": [{"libelle": lib, "valeur": "", "encoded": False}]}),
        ok({}),
        ok({"parametres": [{"libelle": lib, "valeur": nouveau, "encoded": False}]}),
    ])
    route = respx.post(url__startswith=f"{API}parametres.awp").mock(side_effect=lambda req: next(reponses))
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    res = await client.set_parametre(lib, "Bienvenue", confirm=True)
    ecrit = decode_body(route.calls[1].request)["parametres"][0]
    assert ecrit["valeur"] == nouveau
    assert res["coherent"] and res["valeur_apres"] == "Bienvenue"
    await client.aclose()
