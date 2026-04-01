import os
import json
import time
import hmac
import secrets
import functools
import logging
from collections import defaultdict

from flask import Blueprint, jsonify, request, make_response, g

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Production safety check — refuse to start without auth credentials
# ---------------------------------------------------------------------------
if os.environ.get('RAILWAY_ENVIRONMENT') and not os.environ.get('ADMIN_PASSWORD'):
    raise RuntimeError("ADMIN_PASSWORD must be set in production")

admin_pro_bp = Blueprint('admin_pro', __name__, url_prefix='/v2')

# In-memory session store: session_id -> {expires, user_id, username, role}
# Sessions expire after 8 hours. Cleared on process restart (Railway redeploy).
_SESSIONS: dict = {}
_SESSION_TTL = 28800  # 8 hours

# Clear all persisted IP blocks on startup — a fresh deploy should unblock admins
try:
    from state_manager import _get_conn
    with _get_conn() as _conn:
        _conn.execute("DELETE FROM app_state WHERE key LIKE 'ratelimit_%'")
    logger.info("Cleared persisted rate-limit blocks on startup")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter for brute-force protection.
# Tracks failed auth attempts per IP: {ip: [timestamp, ...]}
# After _RATE_LIMIT_MAX failures in _RATE_LIMIT_WINDOW seconds the IP is
# blocked for _RATE_LIMIT_BLOCK_SECS seconds.
# ---------------------------------------------------------------------------
_RATE_LIMIT_WINDOW = 60       # seconds to count failures in
_RATE_LIMIT_MAX = 5           # max failures before block
_RATE_LIMIT_BLOCK_SECS = 900  # 15-minute block
_rate_fail_times: dict = defaultdict(list)   # ip -> [unix_ts, ...]
_rate_blocked_until: dict = {}               # ip -> unix_ts


def _rate_limit_check(ip: str) -> bool:
    """Return True if the IP is currently rate-limited (should be blocked)."""
    now = time.time()
    blocked_until = _rate_blocked_until.get(ip, 0)
    if now < blocked_until:
        return True
    # Also check SQLite persistence (catches blocks from previous process)
    persisted = _load_block(ip)
    if now < persisted:
        _rate_blocked_until[ip] = persisted  # Restore to in-memory cache
        return True
    return False


def _persist_block(ip: str, blocked_until: float) -> None:
    """Persist an IP block to SQLite so it survives process restarts."""
    try:
        from state_manager import _get_conn
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_state(key, value) VALUES(?, ?)",
                (f"ratelimit_{ip}", str(blocked_until))
            )
    except Exception:
        pass  # Don't let persistence failure break rate limiting


def _load_block(ip: str) -> float:
    """Load a persisted IP block timestamp from SQLite."""
    try:
        from state_manager import _get_conn
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key=?", (f"ratelimit_{ip}",)
            ).fetchone()
            return float(row['value']) if row else 0.0
    except Exception:
        return 0.0


def _rate_limit_record_failure(ip: str) -> None:
    """Record a failed auth attempt for *ip*; apply block if threshold exceeded."""
    now = time.time()
    # Prune old timestamps outside the window
    _rate_fail_times[ip] = [t for t in _rate_fail_times[ip] if now - t < _RATE_LIMIT_WINDOW]
    _rate_fail_times[ip].append(now)
    if len(_rate_fail_times[ip]) >= _RATE_LIMIT_MAX:
        blocked_until = now + _RATE_LIMIT_BLOCK_SECS
        _rate_blocked_until[ip] = blocked_until
        _persist_block(ip, blocked_until)  # Persist so block survives restarts
        logger.warning("Rate-limit: blocked IP %s for %ds after %d failures",
                       ip, _RATE_LIMIT_BLOCK_SECS, len(_rate_fail_times[ip]))
        _rate_fail_times[ip] = []  # reset counter after block is applied


def _get_client_ip() -> str:
    """Determine client IP, trusting X-Forwarded-For only on Railway."""
    on_railway = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_SERVICE_NAME'))
    if on_railway:
        return (
            request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr
            or 'unknown'
        )
    return request.remote_addr or 'unknown'


def _rate_limit_clear(ip: str) -> None:
    """Clear failure history for *ip* after a successful authentication."""
    _rate_fail_times.pop(ip, None)
    _rate_blocked_until.pop(ip, None)
    # Also remove the persisted SQLite block so it doesn't reappear after restart
    try:
        from state_manager import _get_conn
        with _get_conn() as conn:
            conn.execute("DELETE FROM app_state WHERE key=?", (f"ratelimit_{ip}",))
    except Exception:
        pass


def _create_session(user_id=None, username='admin', role='owner') -> str:
    sid = secrets.token_hex(20)
    _SESSIONS[sid] = {
        'expires': time.time() + _SESSION_TTL,
        'user_id': user_id or 0,
        'username': username,
        'role': role,
    }
    # Prune expired sessions to avoid unbounded growth
    now = time.time()
    expired = [k for k, v in _SESSIONS.items() if v.get('expires', 0) < now]
    for k in expired:
        del _SESSIONS[k]
    return sid


def _check_session(sid: str):
    """Return session dict if valid, or None."""
    sess = _SESSIONS.get(sid)
    if not sess:
        return None
    if time.time() >= sess.get('expires', 0):
        _SESSIONS.pop(sid, None)
        return None
    return sess


def _credentials_valid() -> bool:
    """Check if the current request carries valid Basic Auth or token credentials.

    All secret comparisons use hmac.compare_digest to prevent timing attacks.

    TOTP MFA: if ADMIN_TOTP_SECRET is set, Basic Auth password must be
    the real password immediately followed by the 6-digit TOTP code.
    Example: password="secret", TOTP="123456" → enter "secret123456".
    """
    admin_password = os.environ.get('ADMIN_PASSWORD', '')
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_token = os.environ.get('ADMIN_TOKEN', '')
    totp_secret = os.environ.get('ADMIN_TOTP_SECRET', '')

    # No security configured — allow only in local dev (no Railway env)
    if not admin_password and not admin_token:
        on_railway = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_SERVICE_NAME'))
        if not on_railway:
            return True  # local dev mode only
        logger.critical("ADMIN: No credentials configured in production — all requests rejected")
        return False

    # Token query param — constant-time comparison
    if admin_token:
        supplied_token = request.args.get('token', '')
        if supplied_token and hmac.compare_digest(supplied_token.encode(), admin_token.encode()):
            return True

    # HTTP Basic Auth — constant-time comparison
    if admin_password:
        auth = request.authorization
        if auth:
            username_ok = hmac.compare_digest(
                (auth.username or '').encode(), admin_username.encode()
            )
            supplied_pw = auth.password or ''
            if totp_secret:
                # TOTP mode: last 6 chars are the TOTP code, rest is the password
                if len(supplied_pw) >= 7:
                    totp_code = supplied_pw[-6:]
                    actual_pw = supplied_pw[:-6]
                    try:
                        import pyotp
                        totp_ok = pyotp.TOTP(totp_secret).verify(totp_code, valid_window=1)
                    except Exception:
                        totp_ok = False
                    password_ok = hmac.compare_digest(actual_pw.encode(), admin_password.encode())
                    if username_ok and password_ok and totp_ok:
                        return True
                # TOTP required but not provided — reject
            else:
                password_ok = hmac.compare_digest(supplied_pw.encode(), admin_password.encode())
                if username_ok and password_ok:
                    return True

    return False


def _credentials_valid_db(username, password):
    """Validate credentials against admin_users table. Returns user dict or None."""
    try:
        from state_manager import StateManager
        state = StateManager()
        user = state.get_admin_user(username)
        if not user or not user.get('is_active'):
            return None
        from werkzeug.security import check_password_hash
        if check_password_hash(user['password_hash'], password):
            return user
    except Exception:
        logger.debug("DB auth check failed, falling back", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Login page HTML
# ---------------------------------------------------------------------------
_LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wheel Doctor — Login</title>
<link rel="icon" type="image/jpeg" href="/static/Banner.jpg">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#1a1a2e;color:#eee;display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-card{background:#16213e;border-radius:12px;padding:40px;width:360px;box-shadow:0 8px 32px rgba(0,0,0,.4)}
.login-card h1{text-align:center;color:#C41230;font-size:1.5rem;margin-bottom:8px}
.login-card .subtitle{text-align:center;color:#888;font-size:.85rem;margin-bottom:28px}
.login-card label{display:block;font-size:.85rem;color:#aaa;margin-bottom:4px}
.login-card input{width:100%;padding:10px 12px;border:1px solid #333;border-radius:6px;background:#0f3460;color:#eee;font-size:.95rem;margin-bottom:16px;outline:none}
.login-card input:focus{border-color:#C41230}
.login-card button{width:100%;padding:12px;background:#C41230;color:#fff;border:none;border-radius:6px;font-size:1rem;cursor:pointer;font-weight:600}
.login-card button:hover{background:#a00f28}
.login-card button:disabled{opacity:.6;cursor:not-allowed}
.error-msg{color:#ff6b6b;font-size:.85rem;text-align:center;margin-bottom:12px;min-height:1.2em}
</style>
</head>
<body>
<div class="login-card">
<h1>Wheel Doctor</h1>
<p class="subtitle">Admin Pro &mdash; Sign In</p>
<div class="error-msg" id="error-msg"></div>
<form id="login-form" autocomplete="on">
<label for="username">Username</label>
<input type="text" id="username" name="username" autocomplete="username" required>
<label for="password">Password</label>
<input type="password" id="password" name="password" autocomplete="current-password" required>
<button type="submit" id="submit-btn">Sign In</button>
</form>
</div>
<script>
(function(){
var form=document.getElementById('login-form'),
    errEl=document.getElementById('error-msg'),
    btn=document.getElementById('submit-btn');
form.addEventListener('submit',function(e){
  e.preventDefault();
  errEl.textContent='';
  btn.disabled=true;
  btn.textContent='Signing in...';
  var body=JSON.stringify({
    username:document.getElementById('username').value,
    password:document.getElementById('password').value
  });
  fetch('/v2/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:body,credentials:'same-origin'})
  .then(function(r){return r.json().then(function(d){return{ok:r.ok,data:d}})})
  .then(function(res){
    if(res.ok && res.data.ok){window.location.href='/v2/';}
    else{errEl.textContent=res.data.error||'Login failed';btn.disabled=false;btn.textContent='Sign In';}
  })
  .catch(function(){errEl.textContent='Network error';btn.disabled=false;btn.textContent='Sign In';});
});
})();
</script>
</body>
</html>"""


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        admin_token = os.environ.get('ADMIN_TOKEN', '')

        on_railway = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_SERVICE_NAME'))

        # Dev mode — no auth configured (local only)
        if not admin_password and not admin_token:
            if not on_railway:
                g.current_user = {'user_id': 0, 'username': 'admin', 'role': 'owner', 'display_name': 'Admin'}
                return f(*args, **kwargs)

        client_ip = _get_client_ip()

        # Check if IP is currently rate-limited
        if _rate_limit_check(client_ip):
            logger.warning("Rate-limit: rejected request from %s", client_ip)
            return make_response(
                jsonify({'ok': False, 'error': 'Too many failed attempts. Try again later.'}),
                429
            )

        # Check session cookie first (set after successful login on the SPA page)
        sid = request.cookies.get('ap_session', '')
        sess = _check_session(sid) if sid else None
        if sess:
            sess['expires'] = time.time() + _SESSION_TTL  # renew on use
            g.current_user = {
                'user_id': sess.get('user_id', 0),
                'username': sess.get('username', 'admin'),
                'role': sess.get('role', 'owner'),
                'display_name': sess.get('display_name', ''),
            }
            return f(*args, **kwargs)

        # Fall back to direct credentials (Basic Auth or ?token=)
        if _credentials_valid():
            _rate_limit_clear(client_ip)
            g.current_user = {'user_id': 0, 'username': 'admin', 'role': 'owner', 'display_name': 'Admin'}
            return f(*args, **kwargs)

        # Only record a rate-limit failure when credentials were actually
        # presented but wrong (brute-force protection).  Missing credentials
        # (e.g. API calls without a session cookie) should NOT count — the
        # dashboard fires 12+ parallel API calls on initial load, and
        # counting each as a failure would instantly block the admin.
        _creds_were_attempted = bool(
            request.authorization  # Basic Auth header present
            or request.args.get('token')
            or request.headers.get('X-Admin-Token')
        )
        if _creds_were_attempted:
            _rate_limit_record_failure(client_ip)

        # Redirect browser page navigations to the login page
        accept_header = request.headers.get('Accept', '')
        is_api_call = (
            request.path.startswith('/v2/api/')
            or (accept_header.startswith('application/json') and 'text/html' not in accept_header)
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )
        if not is_api_call:
            from flask import redirect
            return redirect('/v2/login')

        response = make_response(
            jsonify({'ok': False, 'error': 'Unauthorized'}),
            401
        )
        return response

    return decorated


def json_ok(data):
    return jsonify({'ok': True, 'data': data})


def json_err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


# ---------------------------------------------------------------------------
# Permission decorators for RBAC
# ---------------------------------------------------------------------------
def require_permission(tab_id, need_edit=False):
    """Check that current session user has permission for tab_id."""
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            user = getattr(g, 'current_user', None)
            if not user:
                return json_err('Unauthorized', 401)
            if user.get('role') == 'owner':
                return f(*args, **kwargs)  # Owner bypasses all checks
            from state_manager import StateManager
            state = StateManager()
            perms = state.get_role_permissions(user['role'])
            tab_perm = perms.get(tab_id, {})
            if need_edit and not tab_perm.get('can_edit', False):
                return json_err('Forbidden: insufficient permissions', 403)
            if not tab_perm.get('can_view', False):
                return json_err('Forbidden: insufficient permissions', 403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def require_role(role_name):
    """Restrict endpoint to a specific role."""
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            user = getattr(g, 'current_user', None)
            if not user or user.get('role') != role_name:
                return json_err('Forbidden: owner access required', 403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# Auth endpoints (login, logout, me, login page)
# ---------------------------------------------------------------------------
@admin_pro_bp.route('/login', methods=['GET'])
def login_page():
    """Serve the login page (no auth required)."""
    return make_response(_LOGIN_PAGE_HTML, 200, {'Content-Type': 'text/html'})


@admin_pro_bp.route('/auth/login', methods=['POST'])
def auth_login():
    """Authenticate user and create session."""
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return json_err('Username and password are required', 400)

    client_ip = _get_client_ip()

    if _rate_limit_check(client_ip):
        return json_err('Too many failed attempts. Try again later.', 429)

    # Try DB auth first
    user = _credentials_valid_db(username, password)
    if user:
        _rate_limit_clear(client_ip)
        from state_manager import StateManager
        state = StateManager()
        state.update_admin_user_login(user['id'])
        sid = _create_session(user_id=user['id'], username=user['username'], role=user['role'])
        resp = make_response(jsonify({
            'ok': True,
            'data': {
                'user_id': user['id'],
                'username': user['username'],
                'display_name': user.get('display_name', ''),
                'role': user['role'],
            }
        }))
        resp.set_cookie('ap_session', sid, max_age=86400, httponly=True, secure=True, samesite='Strict')
        return resp

    # Fallback: env-var auth (for backward compatibility when no DB users)
    admin_password = os.environ.get('ADMIN_PASSWORD', '')
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    if admin_password and hmac.compare_digest(username.encode(), admin_username.encode()) and hmac.compare_digest(password.encode(), admin_password.encode()):
        _rate_limit_clear(client_ip)
        sid = _create_session(user_id=0, username=admin_username, role='owner')
        resp = make_response(jsonify({
            'ok': True,
            'data': {
                'user_id': 0,
                'username': admin_username,
                'display_name': 'Owner',
                'role': 'owner',
            }
        }))
        resp.set_cookie('ap_session', sid, max_age=86400, httponly=True, secure=True, samesite='Strict')
        return resp

    _rate_limit_record_failure(client_ip)
    return json_err('Invalid username or password', 401)


@admin_pro_bp.route('/auth/logout', methods=['POST'])
def auth_logout():
    """Clear session cookie."""
    sid = request.cookies.get('ap_session', '')
    _SESSIONS.pop(sid, None)
    resp = make_response(jsonify({'ok': True}))
    resp.delete_cookie('ap_session')
    return resp


@admin_pro_bp.route('/auth/me', methods=['GET'])
@require_auth
def auth_me():
    """Return current user info + permissions."""
    user = getattr(g, 'current_user', None) or {'user_id': 0, 'username': 'admin', 'role': 'owner'}
    from state_manager import StateManager, ALL_TAB_IDS
    state = StateManager()
    if user.get('role') == 'owner':
        permissions = {tab: {'can_view': True, 'can_edit': True} for tab in ALL_TAB_IDS}
    else:
        permissions = state.get_role_permissions(user.get('role', 'technician'))
    return json_ok({
        'user_id': user.get('user_id', 0),
        'username': user.get('username', 'admin'),
        'display_name': user.get('display_name', ''),
        'role': user.get('role', 'owner'),
        'permissions': permissions,
    })


# Import sub-modules last so that blueprint and helpers are defined before
# registration. Each module calls register(admin_pro_bp, require_auth) at
# import time.
from .api import bookings, analytics, communications, system, customers, quotes, photos, waitlist, route, competitors, manual_booking  # noqa: F401, E402
from .api import users as users_api  # noqa: F401, E402
users_api.register(admin_pro_bp, require_auth, require_permission=require_permission)
from .ui import main as ui_main  # noqa: F401, E402
ui_main.register(admin_pro_bp, require_auth)  # register SPA route
