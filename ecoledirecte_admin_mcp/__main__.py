"""Point d'entrée : python -m ecoledirecte_admin_mcp (ou `ecoledirecte-admin-mcp`)."""
from .server import mcp


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
