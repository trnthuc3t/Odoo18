# -*- coding: utf-8 -*-
"""Auth Portal Controller - Ket noi React Frontend voi Odoo Portal User."""

from odoo import http
from odoo.http import request, Response
from contextlib import contextmanager
import json
import logging
import secrets
import re

_logger = logging.getLogger(__name__)

ALLOWED_ORIGIN = 'http://localhost:3000'


def _get_request_origin():
    """Lấy origin thực tế từ request để hỗ trợ CORS chính xác."""
    origin = request.httprequest.headers.get('Origin', '')
    allowed_origins = ['http://localhost:3000', 'http://127.0.0.1:3000']
    return origin if origin in allowed_origins else ALLOWED_ORIGIN


def _make_response(payload, status=200):
    origin = _get_request_origin()
    headers = [
        ('Content-Type', 'application/json'),
        ('Access-Control-Allow-Origin', origin),
        ('Access-Control-Allow-Credentials', 'true'),
        ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
        ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CSRF-Token, X-Requested-With'),
        ('Access-Control-Max-Age', '86400'),
        ('Cache-Control', 'no-store'),
    ]
    return Response(json.dumps(payload), status=status, headers=headers)


def _preflight_response():
    """Trả về response cho CORS preflight (OPTIONS) request."""
    origin = _get_request_origin()
    return Response(
        status=204,
        headers=[
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CSRF-Token, X-Requested-With'),
            ('Access-Control-Max-Age', '86400'),
        ]
    )


def _parse_json(data):
    try:
        return json.loads(data.decode('utf-8')) if isinstance(data, bytes) else json.loads(data)
    except Exception:
        return None


def _is_valid_email(email):
    return bool(re.match(r'^[\w.\+\-]+@[\w.\-]+\.\w{2,}$', email))


class AuthPortalController(http.Controller):

    # ── CORS Preflight ───────────────────────────────────────────────────────

    @http.route('/api/auth/register', type='http', auth='public', methods=['OPTIONS'], csrf=False)
    def register_options(self, **kwargs):
        return _preflight_response()

    # ── Register ─────────────────────────────────────────────────────────────

    @http.route('/api/auth/register', type='http', auth='public', methods=['POST'], csrf=False)
    def register(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'success': False, 'error': 'JSON khong hop le'}, 400)

        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        phone = (data.get('phone') or '').strip()
        password = data.get('password') or ''

        errors = {}
        if not name or len(name) < 2:
            errors['name'] = 'Ho va ten phai it nhat 2 ky tu'
        if not email:
            errors['email'] = 'Email khong duoc de trong'
        elif not _is_valid_email(email):
            errors['email'] = 'Dinh dang email khong hop le'
        if not password or len(password) < 8:
            errors['password'] = 'Mat khau phai it nhat 8 ky tu'

        if errors:
            return _make_response({
                'success': False,
                'error': 'Validation failed',
                'data': {'validation_errors': errors}
            }, 400)

        # Kiem tra email da ton tai chua
        existing = request.env['res.users'].sudo().search([('login', '=', email)], limit=1)
        if existing:
            return _make_response({
                'success': False,
                'error': 'Email da duoc su dung',
                'error_code': 'EMAIL_EXISTS'
            }, 409)

        try:
            # Lay portal group va company chinh
            portal_group = request.env.ref('base.group_portal')
            company = request.env['res.company'].sudo().search([], limit=1, order='id')

            # Tao portal user - KHONG truyen password truc tiep vao create()
            # ma set hash sau qua SQL de dam bao format dung (Odoo 18 dung pbkdf2_sha512)
            user = request.env['res.users'].sudo().with_context(
                no_reset_password=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                tracking_disable=True,
            ).create({
                'name': name,
                'login': email,
                'email': email,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'groups_id': [(6, 0, [portal_group.id])],
            })

            # Set password bang SQL ngay sau khi tao - dung format Odoo 18
            crypt_ctx = request.env['res.users'].sudo()._crypt_context()
            user_id = user.id
            crypt_value = crypt_ctx.hash(password)
            request.cr.execute(
                "UPDATE res_users SET password = %s WHERE id = %s",
                [crypt_value, user_id]
            )
            request.cr.commit()  # Commit de luu password hash ngay

            # Gan phone vao partner (res.users khong co truong phone, chi co res.partner)
            if phone:
                user.partner_id.sudo().write({'phone': phone})

        except Exception as e:
            _logger.warning("Failed to create portal user: %s", str(e))
            return _make_response({'success': False, 'error': 'Khong the tao tai khoan: ' + str(e)}, 500)

        _logger.info("Portal user registered: id=%s, email=%s", user.id, email)

        return _make_response({
            'success': True,
            'data': {
                'user': {
                    'id': user.id,
                    'name': user.name,
                    'email': user.login,
                    'partner_id': user.partner_id.id,
                    'phone': phone,
                },
                'token': 'token_%s_%s' % (user.id, secrets.token_hex(8)),
                'expires_in': 7 * 24 * 3600,
            }
        }, 201)

    # ── Login ───────────────────────────────────────────────────────────────

    @http.route('/api/auth/login', type='http', auth='public', methods=['OPTIONS'], csrf=False)
    def login_options(self, **kwargs):
        return _preflight_response()

    @http.route('/api/auth/login', type='http', auth='public', methods=['POST'], csrf=False)
    def login(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'success': False, 'error': 'JSON khong hop le'}, 400)

        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not email or not password:
            return _make_response({
                'success': False,
                'error': 'Email va mat khau khong duoc de trong'
            }, 400)

        try:
            auth_result = request.session.authenticate(request.env.cr.dbname, {
                'type': 'password',
                'login': email,
                'password': password,
            })
            if not auth_result:
                return _make_response({'success': False, 'error': 'Email hoac mat khau khong dung'}, 401)
            uid = auth_result.get('uid')
        except Exception as e:
            _logger.warning("Authentication failed for %s: %s", email, str(e))
            return _make_response({'success': False, 'error': 'Email hoac mat khau khong dung'}, 401)

        user = request.env['res.users'].sudo().browse(uid)
        if not user.exists():
            return _make_response({'success': False, 'error': 'Tai khoan khong ton tai'}, 401)

        csrf_token = request.csrf_token()
        _logger.info("User logged in: id=%s, email=%s", uid, email)

        return _make_response({
            'success': True,
            'data': {
                'user': {
                    'id': uid,
                    'name': user.name,
                    'email': user.login,
                    'partner_id': user.partner_id.id,
                },
                'token': 'token_%s_%s' % (uid, secrets.token_hex(8)),
                'session_id': request.session.sid,
                'csrf_token': csrf_token,
                'expires_in': 7 * 24 * 3600,
            }
        })

    # ── Logout ──────────────────────────────────────────────────────────────

    @http.route('/api/auth/logout', type='http', auth='user', methods=['POST'], csrf=False)
    def logout(self, **kwargs):
        user_id = request.env.user.id
        request.session.logout()
        _logger.info("User logged out: user=%s", user_id)
        return _make_response({'success': True, 'data': {'message': 'Dang xuat thanh cong'}})

    # ── Me ──────────────────────────────────────────────────────────────────

    @http.route('/api/auth/me', type='http', auth='user', methods=['POST'], csrf=False)
    def me(self, **kwargs):
        try:
            user = request.env.user
            partner = user.partner_id
            return _make_response({
                'success': True,
                'data': {
                    'user': {
                        'id': user.id,
                        'name': user.name,
                        'email': user.login,
                        'phone': partner.phone or '',
                        'partner_id': partner.id,
                    }
                }
            })
        except Exception as e:
            _logger.error("Error getting current user: %s", str(e))
            return _make_response({'success': False, 'error': 'Khong the lay thong tin user'}, 500)

    # ── Forgot Password ─────────────────────────────────────────────────────

    @http.route('/api/auth/forgot-password', type='http', auth='public', methods=['OPTIONS'], csrf=False)
    def forgot_password_options(self, **kwargs):
        return _preflight_response()

    @http.route('/api/auth/forgot-password', type='http', auth='public', methods=['POST'], csrf=False)
    def forgot_password(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'success': False, 'error': 'JSON khong hop le'}, 400)

        email = (data.get('email') or '').strip().lower()
        if not email or not _is_valid_email(email):
            return _make_response({'success': False, 'error': 'Email khong hop le'}, 400)

        try:
            user = request.env['res.users'].sudo().search([('login', '=', email)], limit=1)
            if user.exists():
                user.with_context(create_user=False).action_reset_password()
                _logger.info("Password reset requested for: %s", email)
        except Exception as e:
            _logger.warning("Forgot password error for %s: %s", email, str(e))

        return _make_response({
            'success': True,
            'data': {'message': 'Da gui lien ket dat lai mat khau'}
        })

    # ── Refresh Token ───────────────────────────────────────────────────────

    @http.route('/api/auth/refresh', type='http', auth='user', methods=['POST'], csrf=False)
    def refresh_token(self, **kwargs):
        user = request.env.user
        return _make_response({
            'success': True,
            'data': {
                'token': 'token_%s_%s' % (user.id, secrets.token_hex(8)),
                'expires_in': 7 * 24 * 3600,
            }
        })

    # ── Set API Key (admin only) ────────────────────────────────────────────

    @http.route('/api/auth/api-key/set', type='http', auth='user', methods=['POST'], csrf=False)
    def set_api_key(self, **kwargs):
        if request.env.user.id != 2:
            return _make_response({'success': False, 'error': 'Chi tai khoan Admin co quyen'}, 403)

        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'success': False, 'error': 'JSON khong hop le'}, 400)

        new_key = (data.get('api_key') or '').strip()
        if not new_key or len(new_key) < 8:
            return _make_response({
                'success': False,
                'error': 'API Key phai it nhat 8 ky tu'
            }, 400)

        try:
            request.env.user.write({'api_key': new_key})
        except Exception as e:
            return _make_response({'success': False, 'error': str(e)}, 400)

        _logger.info("API key updated for admin user (id=2)")
        return _make_response({
            'success': True,
            'data': {'api_key': new_key, 'message': 'API Key da duoc cap nhat'}
        })