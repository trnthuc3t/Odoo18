# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.addons.im_livechat.controllers.main import LivechatController
from odoo.addons.mail.models.discuss.mail_guest import add_guest_to_context

from odoo.addons.tour_base.controllers.auth_helper import _make_response
from ..livechat_identity import (
    clear_livechat_identity,
    format_livechat_identity,
    get_livechat_display_name,
    set_livechat_identity,
)
from datetime import datetime, timedelta


class TourLivechatBridgeApi(http.Controller):

    @http.route('/api/livechat/identity', type='http', auth='user', methods=['POST'], csrf=False)
    def sync_identity(self, **kwargs):
        user = request.env.user
        if not user or not user.exists() or user._is_public():
            return _make_response({
                'code': 401,
                'message': 'Not authenticated',
                'response': None,
            }, 401)

        # `sudo()` only accepts a boolean flag in this Odoo version.
        # Using `sudo(user.id)` triggers AssertionError and returns 500.
        identity = set_livechat_identity(user)
        return _make_response({
            'code': 200,
            'message': 'Livechat identity synchronized',
            'response': {
                'identity': identity,
                'display_name': format_livechat_identity(identity),
            },
        })

    @http.route('/api/livechat/identity/clear', type='http', auth='public', methods=['POST'], csrf=False)
    def clear_identity(self, **kwargs):
        clear_livechat_identity()
        return _make_response({
            'code': 200,
            'message': 'Livechat identity cleared',
            'response': {
                'cleared': True,
            },
        })

    @http.route('/api/livechat/session/reset', type='http', auth='public', methods=['POST'], csrf=False)
    def reset_session(self, **kwargs):
        clear_livechat_identity()
        request.future_response.set_cookie('dgid', '', max_age=0)
        return _make_response({
            'code': 200,
            'message': 'Livechat session reset',
            'response': {
                'cleared': True,
            },
        })

    @http.route('/api/livechat/session/restore', type='http', auth='user', methods=['POST'], csrf=False)
    def restore_session(self, **kwargs):
        user = request.env.user
        if not user or not user.exists() or user._is_public():
            return _make_response({
                'code': 401,
                'message': 'Not authenticated',
                'response': {'restored': False},
            }, 401)

        partner = user.partner_id
        if not partner:
            return _make_response({
                'code': 200,
                'message': 'No partner linked',
                'response': {'restored': False},
            })

        key = 'tour_livechat.guest_token.%d' % partner.id
        token = request.env['ir.config_parameter'].sudo().get_param(key)

        if token:
            expiration = datetime.now() + timedelta(days=365)
            request.future_response.set_cookie(
                'dgid', token, httponly=True, expires=expiration
            )
            return _make_response({
                'code': 200,
                'message': 'Session restored',
                'response': {'restored': True},
            })

        return _make_response({
            'code': 200,
            'message': 'No previous session found',
            'response': {'restored': False},
        })

class TourLivechatController(LivechatController):

    @http.route()
    @add_guest_to_context
    def livechat_init(self, channel_id):
        """Luon hien nut chat neu channel co operator duoc gan, ke ca khi ho offline."""
        result = super().livechat_init(channel_id)
        if isinstance(result, dict) and not result.get('available_for_me'):
            channel = request.env['im_livechat.channel'].sudo().browse(channel_id)
            if channel.exists() and channel.user_ids.filtered(lambda u: u.active):
                result['available_for_me'] = True
        return result

    def _get_guest_name(self):
        # Cho same-origin request: lay ten tu session identity neu co
        display_name = get_livechat_display_name()
        return display_name or super()._get_guest_name()

