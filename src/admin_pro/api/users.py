"""
admin_pro/api/users.py
User management and role permission API endpoints (Owner only).
"""

import logging
from flask import request

from state_manager import StateManager, ALL_TAB_IDS

logger = logging.getLogger(__name__)


def register(bp, require_auth, require_permission=None):
    """Register user management API routes on *bp*."""

    from admin_pro import require_role, json_ok, json_err

    _sm = StateManager()

    # ------------------------------------------------------------------
    # GET /api/users — list all users
    # ------------------------------------------------------------------
    @bp.route('/api/users', methods=['GET'])
    @require_auth
    @require_role('owner')
    def list_users():
        try:
            users = _sm.list_admin_users()
            # Strip password hashes from response
            for u in users:
                u.pop('password_hash', None)
                u.pop('totp_secret', None)
            return json_ok(users)
        except Exception as e:
            logger.error("list_users error: %s", e, exc_info=True)
            return json_err(str(e), 500)

    # ------------------------------------------------------------------
    # POST /api/users — create a new user
    # ------------------------------------------------------------------
    @bp.route('/api/users', methods=['POST'])
    @require_auth
    @require_role('owner')
    def create_user():
        try:
            data = request.get_json(force=True) or {}
            username = (data.get('username') or '').strip().lower()
            password = data.get('password') or ''
            display_name = (data.get('display_name') or '').strip()
            role = (data.get('role') or 'technician').strip().lower()

            if not username:
                return json_err('Username is required', 400)
            if len(password) < 8:
                return json_err('Password must be at least 8 characters', 400)

            valid_roles = {r['role'] for r in _sm.list_roles()}
            if role not in valid_roles:
                return json_err(f'Invalid role: {role}', 400)

            # Check uniqueness
            existing = _sm.get_admin_user(username)
            if existing:
                return json_err('Username already exists', 409)

            from werkzeug.security import generate_password_hash
            pw_hash = generate_password_hash(password)
            user_id = _sm.create_admin_user(username, pw_hash, display_name, role)

            return json_ok({'user_id': user_id, 'username': username, 'role': role})
        except Exception as e:
            logger.error("create_user error: %s", e, exc_info=True)
            return json_err(str(e), 500)

    # ------------------------------------------------------------------
    # PUT /api/users/<user_id> — edit user fields
    # ------------------------------------------------------------------
    @bp.route('/api/users/<int:user_id>', methods=['PUT'])
    @require_auth
    @require_role('owner')
    def edit_user(user_id):
        try:
            data = request.get_json(force=True) or {}
            user = _sm.get_admin_user_by_id(user_id)
            if not user:
                return json_err('User not found', 404)

            updates = {}
            if 'display_name' in data:
                updates['display_name'] = (data['display_name'] or '').strip()
            if 'role' in data:
                new_role = (data['role'] or '').strip().lower()
                valid_roles = {r['role'] for r in _sm.list_roles()}
                if new_role not in valid_roles:
                    return json_err(f'Invalid role: {new_role}', 400)
                # Cannot change role of the last active owner
                if user['role'] == 'owner' and new_role != 'owner':
                    owners = [u for u in _sm.list_admin_users() if u['role'] == 'owner' and u['is_active']]
                    if len(owners) <= 1:
                        return json_err('Cannot change role of the last active owner', 400)
                updates['role'] = new_role
            if 'username' in data:
                new_username = (data['username'] or '').strip().lower()
                if new_username and new_username != user['username']:
                    existing = _sm.get_admin_user(new_username)
                    if existing:
                        return json_err('Username already exists', 409)
                    updates['username'] = new_username
            if 'password' in data and data['password']:
                if len(data['password']) < 8:
                    return json_err('Password must be at least 8 characters', 400)
                from werkzeug.security import generate_password_hash
                updates['password_hash'] = generate_password_hash(data['password'])
            if 'is_active' in data:
                updates['is_active'] = 1 if data['is_active'] else 0

            if updates:
                _sm.update_admin_user(user_id, **updates)

            return json_ok({'updated': True})
        except Exception as e:
            logger.error("edit_user error: %s", e, exc_info=True)
            return json_err(str(e), 500)

    # ------------------------------------------------------------------
    # DELETE /api/users/<user_id> — soft deactivate
    # ------------------------------------------------------------------
    @bp.route('/api/users/<int:user_id>', methods=['DELETE'])
    @require_auth
    @require_role('owner')
    def delete_user(user_id):
        try:
            user = _sm.get_admin_user_by_id(user_id)
            if not user:
                return json_err('User not found', 404)

            # Cannot deactivate the last active owner
            if user['role'] == 'owner' and user['is_active']:
                owners = [u for u in _sm.list_admin_users() if u['role'] == 'owner' and u['is_active']]
                if len(owners) <= 1:
                    return json_err('Cannot deactivate the last active owner', 400)

            _sm.deactivate_admin_user(user_id)
            return json_ok({'deactivated': True})
        except Exception as e:
            logger.error("delete_user error: %s", e, exc_info=True)
            return json_err(str(e), 500)

    # ------------------------------------------------------------------
    # GET /api/roles — list roles with permissions
    # ------------------------------------------------------------------
    @bp.route('/api/roles', methods=['GET'])
    @require_auth
    @require_role('owner')
    def list_roles():
        try:
            roles = _sm.list_roles()
            result = []
            for role in roles:
                perms = _sm.get_role_permissions(role['role'])
                result.append({
                    'role': role['role'],
                    'display_name': role['display_name'],
                    'description': role.get('description', ''),
                    'is_system': bool(role.get('is_system')),
                    'permissions': perms,
                })
            return json_ok({'roles': result, 'all_tabs': ALL_TAB_IDS})
        except Exception as e:
            logger.error("list_roles error: %s", e, exc_info=True)
            return json_err(str(e), 500)

    # ------------------------------------------------------------------
    # PUT /api/roles/<role>/permissions — update role permission matrix
    # ------------------------------------------------------------------
    @bp.route('/api/roles/<role>/permissions', methods=['PUT'])
    @require_auth
    @require_role('owner')
    def update_role_permissions(role):
        try:
            if role == 'owner':
                return json_err('Cannot modify owner role permissions', 400)

            data = request.get_json(force=True) or {}
            permissions = data.get('permissions', {})
            if not permissions:
                return json_err('No permissions provided', 400)

            _sm.update_role_permissions(role, permissions)
            return json_ok({'updated': True})
        except Exception as e:
            logger.error("update_role_permissions error: %s", e, exc_info=True)
            return json_err(str(e), 500)
