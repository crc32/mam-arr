from mcp.server.auth.provider import AccessToken, TokenVerifier


class StaticBearerTokenVerifier:
    """Verify MCP HTTP requests against a single configured bearer token."""

    def __init__(self, expected_token: str, client_id: str = "mamarr-client"):
        self.expected_token = expected_token
        self.client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self.expected_token or token != self.expected_token:
            return None
        return AccessToken(
            token=token,
            client_id=self.client_id,
            scopes=["mcp:read", "mcp:write"],
        )


def build_token_verifier(auth_token: str) -> TokenVerifier | None:
    if not auth_token:
        return None
    return StaticBearerTokenVerifier(auth_token)
