# -*- coding: utf-8 -*-

from odoo import models
from ..livechat_identity import get_livechat_identity


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _find_or_create_persona_for_channel(
        self, guest_name, timezone=None, country_code=None, post_joined_message=True
    ):
        visitor_label = ''
        if (
            self.channel_type == 'livechat'
            and self.anonymous_name
            and self.anonymous_name.strip().lower() not in ('visitor', 'visitors', '')
        ):
            visitor_label = self.anonymous_name.strip()
            if guest_name in ('Visitor', 'Visitors'):
                guest_name = visitor_label

        result = super()._find_or_create_persona_for_channel(
            guest_name,
            timezone=timezone,
            country_code=country_code,
            post_joined_message=post_joined_message,
        )

        guest = result[1] if isinstance(result, tuple) and len(result) > 1 else self.env['mail.guest']
        if visitor_label and guest and guest.exists() and guest.name in ('Visitor', 'Visitors'):
            guest.sudo().write({'name': visitor_label})

        # Luu guest token vao database theo partner de co the khoi phuc
        if guest and guest.exists():
            try:
                identity = get_livechat_identity()
                if identity and identity.get('email'):
                    partner = self.env['res.partner'].sudo().search(
                        [('email', '=', identity['email'])], limit=1
                    )
                    if partner:
                        key = 'tour_livechat.guest_token.%d' % partner.id
                        self.env['ir.config_parameter'].sudo().set_param(
                            key, guest.sudo()._format_auth_cookie()
                        )
            except Exception:
                pass  
        return result

