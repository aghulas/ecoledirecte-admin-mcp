"""Point d'entrée : python -m ecoledirecte_perso_mcp (ou `ecoledirecte-perso-mcp`).

  stdio (défaut, Claude Desktop) :
      python -m ecoledirecte_perso_mcp
  streamable-http (distant, Copilot 365 - authentification Entra ID requise,
  voir le README du dépôt partagé github.com/aghulas/mcp-entra-auth pour les
  variables d'environnement MCP_ENTRA_TENANT_ID / MCP_ENTRA_APP_ID_URI /
  MCP_ENTRA_ALLOWED_GROUP_ID / MCP_ENTRA_PUBLIC_URL) :
      python -m ecoledirecte_perso_mcp --transport streamable-http --port 8002
"""
import argparse

from .server import mcp

# Scope Entra ID propre a ce serveur - jamais partage avec ecoledirecte-admin-mcp,
# charlemagne-mcp ou edumoov-mcp, meme s'ils utilisent tous mcp-entra-auth.
REQUIRED_SCOPE = "EcoleDirectePerso.Read"


def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur MCP EcoleDirecte - espace personnel")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (defaut, Claude Desktop) ou streamable-http (distant, Copilot 365)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="streamable-http seulement")
    parser.add_argument("--port", type=int, default=8002, help="streamable-http seulement")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    from mcp_entra_auth import apply_entra_auth

    apply_entra_auth(mcp, required_scope=REQUIRED_SCOPE)
    mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
