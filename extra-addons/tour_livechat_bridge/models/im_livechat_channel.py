# -*- coding: utf-8 -*-

from odoo import api, fields, models

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