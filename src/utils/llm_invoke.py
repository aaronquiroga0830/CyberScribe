"""Bounded Ollama/LangChain invoke for benchmarks and optional production caps."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def ollama_generate_timeout_s() -> float | None:
    """Seconds per LLM invoke; None = no limit (default UI behavior)."""
    try:
        from config.settings import OLLAMA_GENERATE_TIMEOUT_S

        if OLLAMA_GENERATE_TIMEOUT_S is not None and OLLAMA_GENERATE_TIMEOUT_S > 0:
            return float(OLLAMA_GENERATE_TIMEOUT_S)
    except Exception:
        pass
    return None


def run_with_timeout(fn: Callable[[], T], timeout_s: float) -> T:
    """
    Run fn() in a worker thread with a wall-clock cap.

    On timeout, shuts down the pool without waiting for the still-running Ollama call
    (avoids blocking the pipeline and saturating the GPU queue).
    """
    if timeout_s <= 0:
        return fn()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout as e:
            raise TimeoutError(f"LLM invoke exceeded {timeout_s:.0f}s") from e
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def invoke_chain_with_timeout(chain: Any, inputs: dict[str, Any], *, timeout_s: float | None = None) -> str:
    """
    Run chain.invoke(inputs). If timeout_s is set and exceeded, raise TimeoutError.
    Uses a worker thread so the caller can enforce a wall-clock cap on blocking Ollama calls.
    """
    limit = timeout_s if timeout_s is not None else ollama_generate_timeout_s()
    if not limit or limit <= 0:
        out = chain.invoke(inputs)
        return (out or "").strip() if isinstance(out, str) else str(out or "").strip()

    try:
        out = run_with_timeout(lambda: chain.invoke(inputs), limit)
    except TimeoutError:
        logger.warning("LLM invoke exceeded %.1fs cap", limit)
        raise
    return (out or "").strip() if isinstance(out, str) else str(out or "").strip()
