"""A polite HTTP client for public web services: one request at a time, spaced out, and
retried when the service says it is busy."""

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

_RETRY_STATUSES = {429, 502, 503, 504}


class ServiceError(Exception):
    """A request to an online service failed. The message is meant to be shown to the user."""


class PoliteClient:
    def __init__(
        self,
        service: str,
        *,
        user_agent: str,
        error: type[ServiceError] = ServiceError,
        transport: httpx.AsyncBaseTransport | None = None,
        min_interval: float = 1.1,
        max_retries: int = 4,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service, self._error = service, error
        self._http = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            transport=transport,
            timeout=20,
            follow_redirects=True,
        )
        self._min_interval, self._max_retries = min_interval, max_retries
        self._sleep, self._clock = sleep, clock
        self._lock = asyncio.Lock()
        self._last_request: float | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _wait_turn(self) -> None:
        if self._last_request is not None:
            wait = self._last_request + self._min_interval - self._clock()
            if wait > 0:
                await self._sleep(wait)
        self._last_request = self._clock()

    async def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response | None:
        """GET with rate limiting and retries. None for 404; the service's error for other
        failures."""
        problem = f"{self._service} did not answer"
        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            async with self._lock:  # one request at a time, spaced out
                await self._wait_turn()
                try:
                    response = await self._http.get(url, params=params)
                except httpx.TransportError as exc:
                    problem = f"Cannot reach {self._service} ({type(exc).__name__})"
                    response = None
            if response is not None:
                if response.status_code == 404:
                    return None
                if response.status_code < 400:
                    return response
                if response.status_code not in _RETRY_STATUSES:
                    raise self._error(self._error_text(response))
                problem = f"{self._service} is busy, please try again in a moment"
            if attempt < self._max_retries:
                await self._sleep(_backoff(attempt, response))
        raise self._error(problem)

    def _error_text(self, response: httpx.Response) -> str:
        try:
            body = response.json()
            detail = body.get("error") if isinstance(body, dict) else None
        except ValueError:
            detail = None
        reason = detail or response.reason_phrase
        return f"{self._service} refused the request (HTTP {response.status_code}): {reason}"


def _backoff(attempt: int, response: httpx.Response | None) -> float:
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), 30.0)
    return min(1.5 * 2**attempt, 30.0)
