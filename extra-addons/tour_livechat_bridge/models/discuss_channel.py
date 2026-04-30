# -*- coding: utf-8 -*-

from odoo import models


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _find_or_create_persona_for_channel(
        self, guest_name, timezone=None, country_code=None, post_joined_message=True
    ):
        """Override: khi tao session livechat, doi ten guest tu 'Visitor' thanh
        anonymous_name cua channel (da duoc set tu React loader URL username param).
        Dieu nay dam bao operator thay ten khach hang thay vi 'Visitor' trong chat.
        Dong thoi post notification thong tin khach hang len channel.
        """
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

        # Guest co the da ton tai truoc do (qua guest_token), khi do Odoo
        # se khong tao moi va ten van la Visitor. Cap nhat lai ten o day.
        guest = result[1] if isinstance(result, tuple) and len(result) > 1 else self.env['mail.guest']
        if visitor_label and guest and guest.exists() and guest.name in ('Visitor', 'Visitors'):
            guest.sudo().write({'name': visitor_label})

        # Post notification thong tin khach hang de operator nhin thay ngay
        if visitor_label:
            parts = [p.strip() for p in visitor_label.split('|') if p.strip()]
            lines = ['<b>&#128100; Th&ocirc;ng tin kh&aacute;ch h&agrave;ng:</b>']
            labels = ['H\u1ecd t\u00ean', 'Email', '\u0110i\u1ec7n tho\u1ea1i']
            for label, value in zip(labels, parts):
                lines.append(f'&bull; {label}: {value}')
            self.sudo().message_post(
                body='<br/>'.join(lines),
                message_type='notification',
                subtype_xmlid='mail.mt_comment',
            )

        return result

