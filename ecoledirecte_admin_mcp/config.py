"""Configuration — pilotée par variables d'environnement, aucun secret codé en dur.

Le mot de passe admin vit UNIQUEMENT dans le Trousseau macOS (service
`keychain_service`, compte = identifiant admin). L'identifiant (non secret) peut
venir de ED_ADMIN_IDENTIFIANT ou du fichier ~/.ecoledirecte-admin-mcp/config.json
écrit par `python -m ecoledirecte_admin_mcp.auth setup`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_HOME_DIR = Path(os.environ.get("ED_ADMIN_HOME", str(Path.home() / ".ecoledirecte-admin-mcp")))


@dataclass(frozen=True)
class Settings:
    # --- API (confirmé 15/09/2026, voir docs/cartographie-api-admin.md §2) ---
    # Le front admin.ecoledirecte.com (AngularJS v3.8.4) réécrit chaque appel en :
    #   POST https://api.ecoledirecte.com/v3/admin/<chemin>.awp?verbe=<get|post|put|delete>&<params>
    #   Content-Type: application/x-www-form-urlencoded ; corps : data=<JSON> ; header x-token
    api_base: str = os.environ.get("ED_ADMIN_API_BASE", "https://api.ecoledirecte.com/v3/admin/")
    user_agent: str = os.environ.get(
        "ED_ADMIN_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    )
    timeout_seconds: float = float(os.environ.get("ED_ADMIN_TIMEOUT", "30"))

    # --- Identité / secrets ---
    home_dir: Path = _HOME_DIR
    config_path: Path = _HOME_DIR / "config.json"
    session_path: Path = _HOME_DIR / "session.json"
    identifiant: str | None = os.environ.get("ED_ADMIN_IDENTIFIANT")
    keychain_service: str = os.environ.get("ED_ADMIN_KEYCHAIN_SERVICE", "ecoledirecte-admin-mcp")

    # --- Redaction ---
    # Champs retirés par défaut des fiches utilisateurs (utilisateurs/<type>) :
    # `badge` = n° de badge d'accès/cantine (identifiant physique), `photo` = chemin
    # de fichier interne sans intérêt pour l'usage et potentiellement sensible.
    sensitive_user_fields: tuple[str, ...] = ("badge", "photo")
    # Tout paramètre dont le libellé contient un de ces fragments (insensible à la
    # casse/aux accents) voit sa valeur masquée : clés de plateformes de paiement,
    # certificats, mots de passe SMTP/API, etc. (écran « Règlements en ligne »).
    secret_param_markers: tuple[str, ...] = field(
        default=(
            "cle", "clé", "certificat", "secret", "password", "motdepasse", "mot de passe",
            "mdp", "token", "apikey", "api_key", "iban", "bic", "pspid", "merchant",
        )
    )


SETTINGS = Settings()
