"""Configuration du connecteur « espace personnel » — variables d'environnement.

Aucun secret codé en dur. Le mot de passe du compte personnel (secrétariat) vit
dans le Trousseau macOS (service `ecoledirecte-perso-mcp`), et les jetons de
double authentification (cn/cv, réutilisables) + le dernier X-Token dans un
fichier local hors dépôt.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HOME_DIR = Path(os.environ.get("ED_PERSO_HOME", str(Path.home() / ".ecoledirecte-perso-mcp")))


@dataclass(frozen=True)
class Settings:
    # Hôte de LOGIN (api) et hôte des DONNÉES (apip), confirmés le 16/09/2026.
    login_base: str = os.environ.get("ED_PERSO_LOGIN_BASE", "https://api.ecoledirecte.com/v3")
    data_base: str = os.environ.get("ED_PERSO_DATA_BASE", "https://apip.ecoledirecte.com/v3")
    api_version: str = os.environ.get("ED_PERSO_API_VERSION", "4.101.4")
    annee: str = os.environ.get("ED_PERSO_ANNEE", "2026-2027")
    # Le User-Agent doit rester identique entre login et appels (sinon jeton invalidé).
    user_agent: str = os.environ.get(
        "ED_PERSO_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    )
    timeout_seconds: float = float(os.environ.get("ED_PERSO_TIMEOUT", "30"))

    home_dir: Path = _HOME_DIR
    config_path: Path = _HOME_DIR / "config.json"
    session_path: Path = _HOME_DIR / "session.json"
    identifiant: str | None = os.environ.get("ED_PERSO_IDENTIFIANT")
    keychain_service: str = os.environ.get("ED_PERSO_KEYCHAIN_SERVICE", "ecoledirecte-perso-mcp")

    # Champs retirés par défaut des fiches élèves (schéma réel confirmé 16/09/2026) :
    # date de naissance et n° de badge (identifiant physique) ; `photo` = chemin interne.
    # `email`/`portable` de l'élève sont CONSERVÉS (utiles pour contacter), comme les
    # mails de parents côté serveur admin.
    sensitive_eleve_fields: tuple[str, ...] = ("dateNaissance", "numeroBadge", "photo")


SETTINGS = Settings()
