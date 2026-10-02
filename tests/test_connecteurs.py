"""Applications partenaires (« Mes Applis ») : calcul des clés d'activation (copie
du front), état réel, plan d'activation et garde-fous d'écriture. Données
synthétiques, réseau mocké (respx)."""
from __future__ import annotations

import pytest
import respx

from ecoledirecte_admin_mcp import connecteurs as m
from ecoledirecte_admin_mcp.client import EcoleDirecteAdminClient, ForbiddenEndpointError

from ._helpers import API, decode_body, fake_auth, ok

FMT = {"formatCleParametreSansCible": "Sites/Connecteur/%CODE%/Etablissement/%IDETAB%/",
       "formatCleParametreMultiCible": "Sites/Connecteur/%CODE%/Etablissement/%IDETAB%/%CIBLECOURT%/"}
PAR_PUBLIC = {"code": "APP1", "libelle": "Appli publics ", "isUniversel": True, "isActivationByEtab": False,
              "isActivationByCible": True, "cibles": ["A", "P", "F"], "categories": [31, 39, 14],
              "tabRGPD": [{"rgpdData": "EMAIL", "typeUser": "F"}, {"rgpdData": "NOM_PRENOM", "typeUser": "F"},
                          {"rgpdData": "EMAIL", "typeUser": "A"}], "activerParDefaut": True, **FMT}
PAR_ETAB = {"code": "APP2", "libelle": "Appli etab", "isUniversel": True, "isActivationByEtab": True,
            "isActivationByCible": False, "cibles": ["F"], "categories": [40], **FMT}
CAS = {"code": "APP3", "libelle": "Appli CAS", "isUniversel": True, "isActivationByEtab": True,
       "isActivationByCible": True, "cibles": ["P"], "isCASAuth": True, **FMT}
SPECIFIQUE = {"code": "ROB", "libelle": "Dico", "isUniversel": True, "isActivationByEtab": True,
              "isActivationByCible": True, "cibles": ["E", "F"],
              "formatCleParametreSpecifique": {"Actif": "Sites/Connecteur/Dico/", "RNE": ""}, **FMT}
RGPD = [{"code": "EMAIL", "libelle": "Adresse email"}, {"code": "NOM_PRENOM", "libelle": "Nom et prénom"}]
ETABS = [{"id": 1, "RNE": "0771234X"}]


def test_cles_comme_le_front():
    assert m.cles_activation(PAR_PUBLIC, [1]) == [
        ("Sites/Connecteur/APP1/Etablissement/0/A/Actif", "A"),
        ("Sites/Connecteur/APP1/Etablissement/0/P/Actif", "P"),
        ("Sites/Connecteur/APP1/Etablissement/0/F/Actif", "F")]
    assert m.cles_activation(PAR_ETAB, [1]) == [("Sites/Connecteur/APP2/Etablissement/1/Actif", "*")]
    assert m.cles_activation(SPECIFIQUE, [1]) == [("Sites/Connecteur/Dico/Actif", "E"), ("Sites/Connecteur/Dico/Actif", "F")]
    assert m.cles_activation({"isUniversel": False}, [1]) == []
    assert m.cle(CAS, "RNE", False, 1) == "Sites/Connecteur/APP3/Etablissement/1/RNE"


def test_etat_et_ligne():
    vals = {"Sites/Connecteur/APP1/Etablissement/0/F/Actif": "1",
            "Sites/Connecteur/APP1/Etablissement/0/A/Actif": "0"}
    r = m.ligne(PAR_PUBLIC, vals, [1], {31: "Ecole", 39: "Elémentaire", 14: "Familles"}, RGPD)
    assert r["actif"] and r["etat_par_public"] == {"Personnels": False, "Enseignants": False, "Familles": True}
    assert r["adapte_ecole"] and r["niveaux"] == ["Ecole", "Elémentaire"] and r["libelle"] == "Appli publics"
    assert r["donnees_partagees"] == {"Familles": ["Adresse email", "Nom et prénom"], "Personnels": ["Adresse email"]}
    assert m.ligne({"isUniversel": False, "code": "X"}, {}, [1], {}, [])["actif"] is False


def test_plan_activation_par_public_et_donnees_transmises():
    vals = {"Sites/Connecteur/APP1/Etablissement/0/F/Actif": "0"}
    p = m.plan_activation(PAR_PUBLIC, vals, ETABS, True, ["Familles"], RGPD)
    assert [c["libelle"] for c in p["a_ecrire"]] == ["Sites/Connecteur/APP1/Etablissement/0/F/Actif"]
    assert p["donnees_transmises_a_l_editeur"] == {"Familles": ["Adresse email", "Nom et prénom"]}
    tout = m.plan_activation(PAR_PUBLIC, {k: "1" for k, _ in m.cles_activation(PAR_PUBLIC, [1])}, ETABS, False, None, RGPD)
    assert len(tout["a_ecrire"]) == 3 and all(c["apres"] == "0" for c in tout["a_ecrire"])


def test_plan_cas_renseigne_le_rne_et_refus():
    p = m.plan_activation(CAS, {}, ETABS, True, None, RGPD)
    assert {"libelle": "Sites/Connecteur/APP3/Etablissement/1/RNE", "public": "RNE (CAS)",
            "avant": None, "apres": "0771234X", "change": True} in p["a_ecrire"]
    with pytest.raises(ValueError, match="non universel"):
        m.plan_activation({"isUniversel": False, "libelle": "X"}, {}, ETABS, False, None, RGPD)
    with pytest.raises(ValueError, match="clé d'API"):
        m.plan_activation({**PAR_ETAB, "needAPIKey": True}, {}, ETABS, True, None, RGPD)
    m.plan_activation({**PAR_ETAB, "needAPIKey": True}, {}, ETABS, False, None, RGPD)  # désactiver reste possible
    with pytest.raises(ValueError, match="public par public"):
        m.plan_activation(PAR_ETAB, {}, ETABS, True, ["F"], RGPD)
    with pytest.raises(ValueError, match="non proposé"):
        m.plan_activation(PAR_PUBLIC, {}, ETABS, True, ["Élèves"], RGPD)
    with pytest.raises(ValueError, match="inconnu"):
        m.code_cible("Voisins")


@pytest.mark.parametrize("libelle,valeur", [
    ("Sites/Familles/Actif", "1"),                                  # pas un connecteur
    ("Sites/Connecteur/X/Etablissement/1/APIKey", "abc"),          # clé d'API
    ("Sites/Connecteur/X/Etablissement/1/Actif", "oui"),           # valeur non booléenne
    ("Sites/Connecteur/X/Etablissement/1/RNE", "pas-un-rne"),
    ("Sites/Connecteur/X/Etablissement/1/IDABOCONNECTEUR", "123"),  # paramètre complémentaire
    ("Sites/Familles/Comptabilite/Actif", "0"),                     # pas un connecteur
])
@respx.mock
async def test_ecriture_refusee_avant_tout_appel(tmp_path, libelle, valeur):
    route = respx.post(url__startswith=f"{API}parametres.awp")
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(ForbiddenEndpointError):
        await client.ecrire_activation_connecteur({libelle: valeur})
    assert not route.calls
    await client.aclose()


def test_format_specifique_accepte_par_le_garde_fou():
    import re as _re
    from ecoledirecte_admin_mcp.client import _normalize
    for k in ("Sites/Eleves/ConnecteurAVENRIA/Etablissement_0/Actif", "Sites/Connecteur/4464/Etablissement/0/F/Actif"):
        assert _re.match(r"sites/(connecteurs?/|[a-z]+/connecteur[^/]+/)", _normalize(k))


@respx.mock
async def test_ecriture_un_seul_post_puis_relecture(tmp_path):
    k1, k2 = "Sites/Connecteur/APP1/Etablissement/0/F/Actif", "Sites/Connecteur/APP3/Etablissement/1/RNE"
    route = respx.post(url__startswith=f"{API}parametres.awp").mock(side_effect=[
        ok({"parametres": [{"libelle": k1, "valeur": "1", "encoded": False}]}),
        ok({}),
        ok({"parametres": [{"libelle": k1, "valeur": "0"}, {"libelle": k2, "valeur": "0771234X"}]}),
    ])
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    res = await client.ecrire_activation_connecteur({k1: "0", k2: "0771234X"})
    read1, write, read2 = (c.request for c in route.calls)
    assert write.url.params["verbe"] == "post"
    assert decode_body(write)["parametres"] == [
        {"libelle": k1, "valeur": "0", "encoded": False}, {"libelle": k2, "valeur": "0771234X", "encoded": False}]
    assert res["coherent"] is True
    await client.aclose()
