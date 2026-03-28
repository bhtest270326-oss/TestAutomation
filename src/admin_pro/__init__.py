import os
import functools
import logging

from flask import Blueprint, jsonify, request, make_response

logger = logging.getLogger(__name__)

admin_pro_bp = Blueprint('admin_pro', __name__, url_prefix='/v2')


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_token = os.environ.get('ADMIN_TOKEN', '')

        # If neither password nor token is configured, allow all through (dev mode)
        if not admin_password and not admin_token:
            return f(*args, **kwargs)

        # Check ?token= query param first as a fallback to basic auth
        if admin_token:
            token = request.args.get('token', '')
            if token == admin_token:
                return f(*args, **kwargs)

        # Check HTTP Basic Auth if ADMIN_PASSWORD is set
        if admin_password:
            auth = request.authorization
            if auth and auth.username == admin_username and auth.password == admin_password:
                return f(*args, **kwargs)

            # Auth failed — return 401 with WWW-Authenticate header
            response = make_response(
                jsonify({'ok': False, 'error': 'Unauthorized'}),
                401
            )
            response.headers['WWW-Authenticate'] = 'Basic realm="Admin"'
            return response

        # Token was set but didn't match, and no password set
        response = make_response(
            jsonify({'ok': False, 'error': 'Unauthorized'}),
            401
        )
        response.headers['WWW-Authenticate'] = 'Basic realm="Admin"'
        return response

    return decorated


def json_ok(data):
    return jsonify({'ok': True, 'data': data})


def json_err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


# Import sub-modules last so that blueprint and helpers are defined before
# registration. Each module calls register(admin_pro_bp, require_auth) at
# import time.
from .api import bookings, analytics, communications, system, customers  # noqa: F401, E402
from .ui import main as ui_main  # noqa: F401, E402
ui_main.register(admin_pro_bp, require_auth)  # register SPA route
