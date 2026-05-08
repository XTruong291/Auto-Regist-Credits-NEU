import asyncio
import httpx
from typing import Optional, Dict, Any
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.cookies: Dict[str, str] = {}
        self.session_token: Optional[str] = None
        self.viewstate: Optional[str] = None
        self.eventvalidation: Optional[str] = None
        self.last_activity = datetime.now()
        self.session_timeout = timedelta(minutes=30)
        self.lock = asyncio.Lock()

    async def login(
        self, username: str, password: str, login_url: str, headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Authenticate and establish session."""
        async with self.lock:
            try:
                payload = {
                    "username": username,
                    "password": password,
                }
                response = await self.client.post(
                    login_url,
                    data=payload,
                    headers=headers,
                    timeout=5.0,
                    follow_redirects=True,
                )

                if response.status_code == 200:
                    self.cookies = dict(response.cookies)
                    self.last_activity = datetime.now()
                    logger.debug(f"Login successful for {username}")
                    return True

                logger.warning(f"Login failed with status {response.status_code}")
                return False

            except Exception as e:
                logger.error(f"Login error: {e}")
                return False

    async def is_session_valid(self) -> bool:
        """Check if session is still valid."""
        async with self.lock:
            if not self.cookies:
                return False

            time_since_activity = datetime.now() - self.last_activity
            if time_since_activity > self.session_timeout:
                return False

            return True

    async def update_last_activity(self) -> None:
        """Update session activity timestamp."""
        async with self.lock:
            self.last_activity = datetime.now()

    async def cache_hidden_fields(self, viewstate: str, eventvalidation: str) -> None:
        """Cache ASP.NET hidden fields."""
        async with self.lock:
            self.viewstate = viewstate
            self.eventvalidation = eventvalidation

    async def get_hidden_fields(self) -> Dict[str, str]:
        """Retrieve cached hidden fields."""
        async with self.lock:
            return {
                "__VIEWSTATE": self.viewstate or "",
                "__EVENTVALIDATION": self.eventvalidation or "",
            }

    async def get_cookies(self) -> Dict[str, str]:
        """Get current session cookies."""
        async with self.lock:
            return self.cookies.copy()

    async def clear_session(self) -> None:
        """Clear session data."""
        async with self.lock:
            self.cookies.clear()
            self.session_token = None
            self.viewstate = None
            self.eventvalidation = None
            self.last_activity = datetime.now()


class AuthManager:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.session_manager = SessionManager(client)

    async def pre_login(
        self, username: str, password: str, login_url: str, headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Pre-login before target time."""
        return await self.session_manager.login(username, password, login_url, headers)

    async def validate_session(self) -> bool:
        """Validate session before firing requests."""
        return await self.session_manager.is_session_valid()

    async def auto_relogin_if_needed(
        self,
        username: str,
        password: str,
        login_url: str,
        force: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Auto re-login if session expired."""
        if force or not await self.validate_session():
            return await self.session_manager.login(username, password, login_url, headers)
        return True

    async def extract_hidden_fields(self, html: str) -> Dict[str, str]:
        """Extract ASP.NET hidden fields from HTML."""
        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(html)
            viewstate_node = tree.css_first('input[name="__VIEWSTATE"]')
            eventvalidation_node = tree.css_first('input[name="__EVENTVALIDATION"]')

            viewstate = viewstate_node.attributes.get("value", "") if viewstate_node else ""
            eventvalidation = (
                eventvalidation_node.attributes.get("value", "") if eventvalidation_node else ""
            )

            if viewstate or eventvalidation:
                await self.session_manager.cache_hidden_fields(viewstate, eventvalidation)

            return {
                "__VIEWSTATE": viewstate,
                "__EVENTVALIDATION": eventvalidation,
            }
        except Exception as e:
            logger.error(f"Failed to extract hidden fields: {e}")
            return {}

    async def get_session_cookies(self) -> Dict[str, str]:
        """Get current session cookies."""
        return await self.session_manager.get_cookies()
