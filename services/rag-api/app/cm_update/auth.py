import hashlib
import time
import jwt
from fastapi import Request, HTTPException
from .db import now
from app.brand import BRAND


def ensure_user(db, user_id: str, auto_verify: bool = False):
    """Return the local projection of an authenticated identity, creating it once.

    Registration grants NO campus qualification. The only paths that still do are
    a redeemed 7-digit code (`social.redeem_code`), an operator grant
    (`social.set_verified` with `admin`) and the approved pre-enablement snapshot
    (`grandfathered`). A brand-new identity therefore ends this function with no
    `cmui_verification` row at all — `verified=0`, `method IS NULL` — and the
    campus gate refuses it until it is really verified.

    This function used to call `social.ensure_registered_qualification`, which
    wrote `verified=1, method='registered'` on the first authenticated request.
    That call is gone, and it must not come back: a stored `verified=1` from a
    registration is exactly the row the owner now needs to be able to tell apart
    from a real verification. Nothing was rewritten for the rows it already
    wrote; they keep their value and are reported as `'registration_auto'`.
    """
    row = db.one('SELECT * FROM cmui_users WHERE id=?',(user_id,))
    created = False
    if not row:
        handle = 'student-' + hashlib.sha256(user_id.encode()).hexdigest()[:12]
        with db.connect(True) as c:
            c.execute('INSERT OR IGNORE INTO cmui_users(id,name,handle,created_at) VALUES (?,?,?,?)', (user_id,BRAND.default_display_name(),handle,now()))
        row = db.one('SELECT * FROM cmui_users WHERE id=?',(user_id,))
        created = True
    if auto_verify:
        # Test/dev convenience ONLY (CMUI_AUTO_VERIFY_NEW_USERS): lets local and
        # legacy test suites pass the campus gate without issuing real codes.
        # Production validation forbids the flag, and this path never marks
        # users as code-verified. It is the one remaining writer here, it is
        # off by default, and it is not a registration policy: the deployed
        # `campus_qualification_policy` is never consulted in this function.
        from . import social
        if created or not social.verification_status(db, user_id)['verified']:
            social.set_verified(db, user_id, 'grandfathered', 'auto-verify dev flag')
    return row


async def current_user(request: Request):
    cfg, db = request.app.state.cfg, request.app.state.db
    auto_verify = bool(getattr(cfg, 'auto_verify_new_users', False))
    # `campus_qualification_policy` is deliberately NOT read here. It selects how
    # strict the campus access gate is; it must never decide whether an identity
    # is granted a qualification, so the old `registered_active` => auto-grant
    # coupling is gone. The gate that reads the policy lives in app.py's
    # `course_gate` and in ui_extension/mount.py's content authorizer.
    if cfg.auth_mode == 'injected':
        subject = await request.app.state.subject_resolver(request)
        if not isinstance(subject,str) or not subject: raise HTTPException(401,'请登录')
        return ensure_user(db,subject,auto_verify)
    if cfg.auth_mode == 'development':
        # No client-supplied user IDs. This endpoint mode is forbidden by production startup gates.
        token = request.cookies.get('cmui_dev_session','')
        hashed = hashlib.sha256(token.encode()).hexdigest()
        session = db.one('SELECT owner FROM cmui_sessions WHERE token_hash=? AND expires>?',(hashed,time.time()))
        if not session: raise HTTPException(401,'请先选择本机测试账号')
        return ensure_user(db,session['owner'],auto_verify)
    header=request.headers.get('authorization','')
    if not header.startswith('Bearer '): raise HTTPException(401,'请登录')
    try:
        kwargs = {'audience':cfg.clerk_audience} if cfg.clerk_audience else {}
        claims = jwt.decode(header[7:],cfg.clerk_jwt_key,algorithms=['RS256'],issuer=cfg.clerk_issuer,
            options={'require':['exp','nbf','iss','sub','sid'],'verify_aud':bool(cfg.clerk_audience)},leeway=5,**kwargs)
        if claims.get('azp') not in cfg.allowed_origins or claims.get('sts') == 'pending':
            raise ValueError('Invalid session origin/status')
        if not isinstance(claims['sub'],str) or not claims['sub']: raise ValueError('Invalid subject')
        return ensure_user(db,claims['sub'],auto_verify)
    except (jwt.PyJWTError,ValueError,KeyError):
        raise HTTPException(401,'登录状态无效，请重新登录') from None
