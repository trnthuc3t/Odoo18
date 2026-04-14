# -*- coding: utf-8 -*-
"""
AuthHelper - Helper functions chung cho tat ca controllers.
Dung Vite plugin xu ly CORS preflight, khong can route OPTIONS.
"""
import json
import logging

from odoo.http import request, Response

_logger = logging.getLogger(__name__)

ALLOWED_ORIGIN = 'http://localhost:3000'


def _get_request_origin():
    """Lay origin thuc te tu request de ho tro CORS chinh xac."""
    origin = request.httprequest.headers.get('Origin', '')
    allowed_origins = ['http://localhost:3000', 'http://127.0.0.1:3000']
    return origin if origin in allowed_origins else ALLOWED_ORIGIN


def _make_response(payload, status=200):
    """Tra ve JSON response voi day du CORS headers.

    Payload format: {'code': int, 'message': str, 'response': any}
    """
    origin = _get_request_origin()
    return Response(
        json.dumps(payload),
        status=status,
        headers=[
            ('Content-Type', 'application/json'),
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CSRF-Token, X-Requested-With'),
            ('Access-Control-Max-Age', '86400'),
            ('Cache-Control', 'no-store'),
        ]
    )


def _parse_json(data):
    """Parse JSON body tu request."""
    try:
        return json.loads(data.decode('utf-8')) if isinstance(data, bytes) else json.loads(data)
    except Exception:
        return None


def _authenticate():
    """
    Xac thuc bang Bearer token (Authorization header).
    Dung cho API can user da dang nhap (session cookie).

    Tra ve user_id neu thanh cong, False neu that bai.
    """
    token = request.httprequest.headers.get('Authorization', '')
    if not token or not token.startswith('Bearer '):
        return False

    token = token.replace('Bearer ', '').strip()
    if not token:
        return False

    # Kiem tra Odoo session hien tai
    if request.env.uid and request.env.uid > 0:
        return request.env.uid

    return False


def _authenticate_api_key():
    """
    Xac thuc bang API Key (cho bot/system, khong can session).
    Doc token tu Authorization: Bearer <api_key>.

    Tra ve res.users record neu thanh cong, False neu that bai.
    """
    token = request.httprequest.headers.get('Authorization', '')
    if not token or not token.startswith('Bearer '):
        return False

    token = token.replace('Bearer ', '').strip()
    if not token:
        return False

    user = request.env['res.users'].sudo().search([
        ('api_key', '=', token),
    ], limit=1)

    if user:
        request.env.user = user.sudo(user.id)
        return user

    return False
