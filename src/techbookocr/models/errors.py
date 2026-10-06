"""Common error convention for adapters.

Transport failures (server unavailable, timeout, 5xx, worker died) are RAISED by the adapter as TransportError.
Content failures (truncation, looping, unparseable output) are RETURNED by the adapter in PageResult.error
as "<kind>" or "<kind>: <detail>".
"""
from __future__ import annotations


class TransportError(RuntimeError):
    """No reply for infrastructure reasons; the page result must not be cached."""


ERR_TRUNCATED = "truncated"
ERR_LOOPING = "looping"
ERR_PARSE = "parse_error"
