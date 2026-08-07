# -*- coding: utf-8 -*-
"""Shared test helpers.

The important thing here is :class:`Tripwire`. Read its docstring before
writing a "must not be called" stub.
"""


class Tripwire(BaseException):
    """Raised by a stub that must never be called.

    Derives from ``BaseException``, NOT ``Exception``, and that is the whole
    point. The code under test is deliberately written to survive anything its
    collaborators throw:

    * ``unlocker.fetch`` wraps every ladder rung in ``except Exception``,
    * so does its tier-0 share hook and its human-in-the-loop rung,
    * and ``share_extractors.extract`` wraps each extractor the same way.

    ``AssertionError`` is an ``Exception``, so a tripwire raising one gets
    swallowed by those handlers and recorded as an ordinary backend failure.
    The guard test then passes whether or not the forbidden call happened,
    which is the exact opposite of its purpose. Verified by mutation: forcing
    ``fetch`` to call ``_fetch_human`` unconditionally left the guard green.

    ``BaseException`` is not caught by ``except Exception``, so it propagates
    out and fails the test the way it always should have.
    """


def tripwire(message):
    """A stub for any signature that fails loudly if it is ever called."""
    def _boom(*args, **kwargs):
        raise Tripwire(message)
    return _boom
