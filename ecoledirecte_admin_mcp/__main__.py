"""Point d'entrée : python -m ecoledirecte_admin_mcp (ou `ecoledirecte-admin-mcp`).

  stdio (défaut, Claude Desktop) :
      python -m ecoledirecte_admin_mcp
  streamable-http (distant, Copilot 365 - authentification Entra ID requise,
  voir le README du dépôt partagé github.com/aghulas/mcp-entra-auth pour les
  variables d'environnement MCP_ENTRA_TENANT_ID / MCP_ENTRA_APP_ID_URI /
  MCP_ENTRA_ALLOWED_GROUP_ID / MCP_ENTRA_PUBLIC_URL) :
      python -m ecoledirecte_admin_mcp --transport streamable-http --port 8001
"""
import argparse

from .server import mcp

# Scope Entra ID propre a ce serveur - jamais partage avec ecoledirecte-perso-mcp,
# charlemagne-mcp ou edumoov-mcp, meme s'ils utilisent tous mcp-entra-auth.
REQUIRED_SCOPE = "EcoleDirecteAdmin.Read"


def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur MCP EcoleDirecte Admin")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (defaut, Claude Desktop) ou streamable-http (distant, Copilot 365)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="streamable-http seulement")
    parser.add_argument("--port", type=int, default=8001, help="streamable-http seulement")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    # Auth Entra ID attachee juste avant run() - jamais pour stdio, qui n'en a pas
    # besoin (process local deja prive). Voir mcp_entra_auth.apply_entra_auth.
    from mcp_entra_auth import apply_entra_auth

    apply_entra_auth(mcp, required_scope=REQUIRED_SCOPE)
    mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
