from __future__ import annotations

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import PROXIES, REQUEST_RETRIES, REQUEST_TIMEOUT


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        }
    )
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = _build_session()


def get(url: str, *, timeout: int = REQUEST_TIMEOUT, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(REQUEST_RETRIES):
        try:
            response = SESSION.get(url, proxies=PROXIES, timeout=timeout, **kwargs)
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {response.status_code} for {url}")
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - network sources are noisy
            last_error = exc
            if attempt + 1 < REQUEST_RETRIES:
                time.sleep(0.7 * (2**attempt))
    raise RuntimeError(f"GET failed after {REQUEST_RETRIES} attempts: {url}: {last_error}") from last_error


def get_json(url: str, *, timeout: int = REQUEST_TIMEOUT, **kwargs: Any) -> Any:
    return get(url, timeout=timeout, **kwargs).json()


def get_text(url: str, *, timeout: int = REQUEST_TIMEOUT, **kwargs: Any) -> str:
    return get(url, timeout=timeout, **kwargs).text
