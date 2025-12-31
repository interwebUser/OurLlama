from __future__ import annotations
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

DEFAULT_HEADERS = {
    "User-Agent": "ollama-model-catalog/0.1 (polite crawler)"
}

class FetchError(RuntimeError):
    pass

@retry(
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, FetchError)),
)
def fetch_text(url: str, timeout_s: float = 30.0, headers: dict | None = None) -> str:
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=hdrs) as client:
        r = client.get(url)
        if r.status_code == 429 or r.status_code >= 500:
            raise FetchError(f"Temporary failure {r.status_code} for {url}")
        r.raise_for_status()
        return r.text
