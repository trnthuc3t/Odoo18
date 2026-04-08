from odoo import api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    @api.model
    def _get_mail_params(self, move, move_data):
        mail_params = super()._get_mail_params(move, move_data)
        if not mail_params:
            return mail_params

        mail_template = move_data.get('mail_template')
        mail_lang = move_data.get('mail_lang')
        if mail_template and mail_lang:
            reply_to = self._get_mail_default_field_value_from_template(
                mail_template, mail_lang, move, 'reply_to'
            )
            if reply_to:
                mail_params['reply_to'] = reply_to

        return mail_params
