"""Context tracking for per-request attribution.

This module provides a registry-based approach for tracking multiple concurrent
requests. Unlike the previous single-slot design, this handles concurrent requests
correctly by storing contexts in a dict keyed by request_id.

Since asyncio is single-threaded, no locks are needed for the registry operations.
The monitor iterates all active contexts when blocking is detected.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(slots=True)
class RequestContext:
    """Context information for a single request.

    Attributes:
        request_id: Unique identifier for this request.
        path: The request path (e.g., "/api/users").
        method: HTTP method (GET, POST, etc.).
        start_time: Monotonic timestamp when request started.
        blocking_events: List of (lag_ms, timestamp) tuples for blocking detected.
    """

    request_id: str
    path: str
    method: str
    start_time: float = field(default_factory=time.monotonic)
    blocking_events: list[tuple[float, float]] = field(default_factory=list)

    def record_blocking(self, lag_ms: float) -> None:
        """Record a blocking event for this request."""
        self.blocking_events.append((lag_ms, time.monotonic()))

    @property
    def total_blocking_ms(self) -> float:
        """Sum of all blocking event durations."""
        return sum(lag for lag, _ in self.blocking_events)

    @property
    def blocking_count(self) -> int:
        """Number of blocking events detected."""
        return len(self.blocking_events)


class RequestRegistry:
    """Registry of active request contexts.

    This class manages multiple concurrent request contexts, storing them
    in a dict keyed by request_id. This allows the monitor to correctly
    attribute blocking events to all active requests.

    No locks are needed since asyncio is single-threaded - all operations
    happen on the same thread within the event loop.
    """

    __slots__ = ("_contexts",)

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._contexts: dict[str, RequestContext] = {}

    def register(self, ctx: RequestContext) -> None:
        """Register a new active request context.

        Args:
            ctx: The request context to register.
        """
        self._contexts[ctx.request_id] = ctx

    def unregister(self, request_id: str) -> RequestContext | None:
        """Remove a request context when the request completes.

        Args:
            request_id: The ID of the request to unregister.

        Returns:
            The removed context, or None if not found.
        """
        return self._contexts.pop(request_id, None)

    def get(self, request_id: str) -> RequestContext | None:
        """Get a specific request context by ID.

        Args:
            request_id: The ID of the request to retrieve.

        Returns:
            The request context, or None if not found.
        """
        return self._contexts.get(request_id)

    def get_all_active(self) -> Iterator[RequestContext]:
        """Iterate all currently active request contexts.

        This is used by the monitor to attribute blocking events
        to all requests that were active when blocking occurred.

        Yields:
            Each active RequestContext.
        """
        yield from self._contexts.values()

    def active_count(self) -> int:
        """Get the number of currently active requests.

        Returns:
            The count of active requests.
        """
        return len(self._contexts)

    def clear(self) -> None:
        """Clear all contexts.

        Used for testing and shutdown cleanup.
        """
        self._contexts.clear()


# Global registry instance
_registry = RequestRegistry()


def get_registry() -> RequestRegistry:
    """Get the global request registry.

    Returns:
        The global RequestRegistry instance.
    """
    return _registry


def register_request(ctx: RequestContext) -> None:
    """Register a request context in the global registry.

    Args:
        ctx: The request context to register.
    """
    _registry.register(ctx)


def unregister_request(request_id: str) -> RequestContext | None:
    """Unregister a request context from the global registry.

    Args:
        request_id: The ID of the request to unregister.

    Returns:
        The removed context, or None if not found.
    """
    return _registry.unregister(request_id)


def get_active_requests() -> Iterator[RequestContext]:
    """Get all active request contexts.

    Yields:
        Each active RequestContext.
    """
    return _registry.get_all_active()


# Backward compatibility aliases
# These maintain the old API but now work correctly with concurrent requests


def get_current_request() -> RequestContext | None:
    """Get any active request context.

    Note: With multiple concurrent requests, this returns an arbitrary
    active request. For correct attribution, use get_active_requests()
    to iterate all active contexts.

    Returns:
        An active RequestContext, or None if no requests are active.
    """
    for ctx in _registry.get_all_active():
        return ctx
    return None


def set_current_request(ctx: RequestContext) -> str:
    """Register a request context and return its ID for cleanup.

    This is a compatibility wrapper around register_request().

    Args:
        ctx: The request context to register.

    Returns:
        The request_id (used as token for reset_current_request).
    """
    _registry.register(ctx)
    return ctx.request_id


def reset_current_request(request_id: str) -> None:
    """Unregister a request context by its ID.

    This is a compatibility wrapper around unregister_request().

    Args:
        request_id: The request ID returned by set_current_request.
    """
    _registry.unregister(request_id)
