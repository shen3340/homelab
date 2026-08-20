import os

from fastmcp import FastMCP

from rag import search_documents


MCP_HOST = os.getenv(
    "MCP_HOST",
    "0.0.0.0",
)

MCP_PORT = int(
    os.getenv(
        "MCP_PORT",
        "8001",
    )
)


mcp = FastMCP(
    "Homelab Documentation",
)


@mcp.tool()
def search_homelab_docs(
    query: str,
    limit: int = 5,
) -> str:
    """
    Search homelab documentation stored in BookStack/Qdrant.

    Use this when answering questions about:
    - NAS
    - Docker
    - Portainer
    - Qdrant
    - Ollama
    - Open WebUI
    - BookStack
    - networking
    - Tailscale
    - homelab services
    """

    results = search_documents(
        query=query,
        limit=limit,
    )

    if not results:
        return "No relevant homelab documentation found."

    output = []

    for index, result in enumerate(results, start=1):
        output.append(
            "\n".join(
                [
                    f"## Result {index}",
                    f"Title: {result.get('title')}",
                    f"Score: {result.get('score')}",
                    f"URL: {result.get('url')}",
                    f"Page ID: {result.get('page_id')}",
                    "",
                    result.get("text") or "",
                ]
            )
        )

    return "\n\n---\n\n".join(output)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
    )