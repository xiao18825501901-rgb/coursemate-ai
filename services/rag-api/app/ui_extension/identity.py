"""Verified-subject resolution for the injected UI extension.

The new UI must not invent a second authentication system. `cm_update` in
``injected`` mode asks the host for the subject of the current request, and the
only trustworthy source is the Clerk verification that :mod:`app.auth` already
performs for every other V3 route.

A mounted sub-application sees *itself* as ``request.app``, so this resolver is
bound to the host application at mount time instead of reaching through
``request.app``.
"""

from fastapi import FastAPI, HTTPException, Request


def clerk_subject_resolver(host_app: FastAPI):
    """Return a resolver bound to the host application's verified identity.

    Raises ``HTTPException(401)`` rather than the host's ``ApiError``: the
    resolver runs inside the mounted sub-application, which owns its own exception
    handlers, so the 401 must be raised in that application's own vocabulary.
    """

    async def resolve(request: Request) -> str:
        verifier = host_app.state.auth_verifier
        subject = verifier.authenticate(request)
        if not isinstance(subject, str) or not subject:
            raise HTTPException(status_code=401, detail="请登录")
        return subject

    return resolve
