import httpx
from typing import Any


LOGIN_URL = "https://tinchi-api.neu.edu.vn/api/Auth/Login"


class LoginFailedException(Exception):
    """Raised when login credentials are invalid or login flow fails."""


class RateLimitException(Exception):
    """Raised when the login endpoint rate-limits requests."""


def _extract_jwt_token(payload: Any) -> str:
    """Extract JWT token from common response shapes."""
    if not isinstance(payload, dict):
        raise LoginFailedException("Login response is not a JSON object.")

    token_candidates = [
        payload.get("token"),
        payload.get("access_token"),
        payload.get("jwt"),
        (payload.get("data") or {}).get("token") if isinstance(payload.get("data"), dict) else None,
        (payload.get("result") or {}).get("token") if isinstance(payload.get("result"), dict) else None,
    ]

    for token in token_candidates:
        if isinstance(token, str) and token.strip():
            return token.strip()

    raise LoginFailedException("JWT token not found in login response.")


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    """
    Authenticate with the NEU API and return raw JWT token.

    Raises:
        LoginFailedException: For 401/403 and other login failures.
        RateLimitException: For 429 rate limit responses.
    """
    payload = {
        "username": username,
        "password": password,
    }

    try:
        response = await client.post(LOGIN_URL, json=payload)
    except httpx.TimeoutException as exc:
        raise LoginFailedException("Login request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LoginFailedException(f"Login request failed: {exc}") from exc

    if response.status_code == 429:
        raise RateLimitException("Too many login attempts (429).")

    if response.status_code in (401, 403):
        raise LoginFailedException(f"Login rejected with status {response.status_code}.")

    if response.status_code >= 400:
        raise LoginFailedException(f"Login failed with status {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise LoginFailedException("Login response is not valid JSON.") from exc

    try:
        return _extract_jwt_token(data)
    except Exception as exc:
        if isinstance(exc, LoginFailedException):
            raise
        raise LoginFailedException(f"Failed to parse JWT token: {exc}") from exc
