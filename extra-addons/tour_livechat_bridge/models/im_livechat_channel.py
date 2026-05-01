# -*- coding: utf-8 -*-

from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.http import request as http_request

from ..livechat_identity import get_livechat_display_name


class ImLivechatChannel(models.Model):
    _inherit = 'im_livechat.channel'

    @api.depends('user_ids', 'user_ids.active', 'user_ids.im_status')
    def _compute_available_operator_ids(self):
        """Hien nut chat ke ca khi operator offline, mien la duoc gan vao channel."""
        super()._compute_available_operator_ids()
        for channel in self:
            if not channel.available_operator_ids and channel.user_ids:
                channel.available_operator_ids = channel.user_ids.filtered(lambda u: u.active)

    def _get_livechat_discuss_channel_vals(
        self,
        anonymous_name,
        previous_operator_id=None,
        chatbot_script=None,
        user_id=None,
        country_id=None,
        lang=None,
    ):
        vals = super()._get_livechat_discuss_channel_vals(
            anonymous_name,
            previous_operator_id=previous_operator_id,
            chatbot_script=chatbot_script,
            user_id=user_id,
            country_id=country_id,
            lang=lang,
        )
        if not vals:
            return vals

        display_name = get_livechat_display_name()
        if not display_name:
            return vals

        operator_name = ''
        if vals.get('livechat_operator_id'):
            operator = self.env['res.partner'].browse(vals['livechat_operator_id'])
            operator_name = operator.user_livechat_username or operator.name or ''

        vals['name'] = ' '.join(part for part in [display_name, operator_name] if part)
        if not user_id:
            vals['anonymous_name'] = display_name
        return vals

    def get_livechat_info(self, username=None):
        info = super().get_livechat_info(username=username)
        try:
            # When the livechat loader is requested cross-origin (e.g., from a React
            # embed at a different port), return the requester's origin as server_url.
            # This makes params.serverURL === window.origin in the widget, so the bus
            # service creates a same-origin worker instead of a data: URL worker.
            # Same-origin workers have no cookie restriction issues for WebSocket auth.
            origin = http_request.httprequest.headers.get('Origin', '')
            referer = http_request.httprequest.headers.get('Referer', '')
            ref_url = origin or referer
            if ref_url:
                parsed = urlparse(ref_url)
                ref_origin = f"{parsed.scheme}://{parsed.netloc}"
                base_url = info.get('server_url', '').rstrip('/')
                if ref_origin and ref_origin != base_url:
                    info['server_url'] = ref_origin
        except Exception:
            pass
        return info