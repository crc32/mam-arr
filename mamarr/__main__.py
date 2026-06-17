"""MAMArr MCP server entry point."""

import argparse
import asyncio
import sys

import uvicorn

from mamarr.config import settings
from mamarr.server import create_mcp_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MAMArr MCP audiobook service")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio for local MCP clients)",
    )
    parser.add_argument("--host", default=settings.host, help="HTTP bind host")
    parser.add_argument("--port", type=int, default=settings.port, help="HTTP bind port")
    parser.add_argument(
        "--ssl-cert",
        default=settings.ssl_cert_file,
        help="TLS certificate file for direct HTTPS",
    )
    parser.add_argument(
        "--ssl-key",
        default=settings.ssl_key_file,
        help="TLS private key file for direct HTTPS",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.transport == "stdio":
        mcp = create_mcp_server(require_http_auth=False)
        mcp.run(transport="stdio")
        return

    if not settings.mcp_auth_token:
        print("ERROR: MCP_AUTH_TOKEN must be set for streamable-http transport.", file=sys.stderr)
        sys.exit(1)

    mcp = create_mcp_server(require_http_auth=True)
    app = mcp.streamable_http_app()

    ssl_kwargs = {}
    if args.ssl_cert and args.ssl_key:
        ssl_kwargs["ssl_certfile"] = args.ssl_cert
        ssl_kwargs["ssl_keyfile"] = args.ssl_key
        scheme = "https"
    else:
        scheme = "http"

    print(f"Starting MAMArr MCP on {scheme}://{args.host}:{args.port}/mcp")
    if scheme == "http":
        print("Tip: set SSL_CERT_FILE and SSL_KEY_FILE (or --ssl-cert/--ssl-key) for direct HTTPS.")

    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        **ssl_kwargs,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
