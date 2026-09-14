import hashlib
import time
import jwt
from fastapi import Request, HTTPException
from .db import now


def ensure_user(db, user_id: str):
    row = db.one('SELECT * FROM cmui_users WHERE id=?',(user_id,))
    if not row:
        handle = 'student-' + hashlib.sha256(user_id.encode()).hexdigest()[:12]
        with db.connect(True) as c:
            c.execute('INSERT OR IGNORE INTO cmui_users(id,name,handle,created_at) VALUES (?,?,?,?)', (user_id,'CourseMate 同学',handle,now()))
        row = db.one('SELECT * FROM cmui_users WHERE id=?',(user_id,))
    return row


async def current_user(request: Request):
    cfg, db = request.app.state.cfg, request.app.state.db
    if cfg.auth_mode == 'injected':
        subject = await request.app.state.subject_resolver(request)
        if not isinstance(subject,str) or not subject: raise HTTPException(401,'请登录')
        return ensure_user(db,subject)
    if cfg.auth_mode == 'development':
        # No client-supplied user IDs. This endpoint mode is forbidden by production startup gates.
        token = request.cookies.get('cmui_dev_session','')
        hashed = hashlib.sha256(token.encode()).hexdigest()
        session = db.one('SELECT owner FROM cmui_sessions WHERE token_hash=? AND expires>?',(hashed,time.time()))
        if not session: raise HTTPException(401,'请先选择本机测试账号')
        return ensure_user(db,session['owner'])
    header=request.headers.get('authorization','')
    if not header.startswith('Bearer '): raise HTTPException(401,'请登录')
    try:
        kwargs = {'audience':cfg.clerk_audience} if cfg.clerk_audience else {}
        claims = jwt.decode(header[7:],cfg.clerk_jwt_key,algorithms=['RS256'],issuer=cfg.clerk_issuer,
            options={'require':['exp','nbf','iss','sub','sid'],'verify_aud':bool(cfg.clerk_audience)},leeway=5,**kwargs)
        if claims.get('azp') not in cfg.allowed_origins or claims.get('sts') == 'pending':
            raise ValueError('Invalid session origin/status')
        if not isinstance(claims['sub'],str) or not claims['sub']: raise ValueError('Invalid subject')
        return ensure_user(db,claims['sub'])
    except (jwt.PyJWTError,ValueError,KeyError):
        raise HTTPException(401,'登录状态无效，请重新登录') from None
