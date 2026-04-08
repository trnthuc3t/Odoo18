from odoo import api, models


class MailComposeMessage(models.TransientModel):
    _inherit = 'mail.compose.message'

    def _prepare_mail_values_rendered(self, res_ids):
        """Override to include reply_to from the template when in monorecord comment mode.
        The base method omits reply_to, ignoring any reply_to configured in the mail template.
        """
        values_all = super()._prepare_mail_values_rendered(res_ids)
        if self.reply_to:
            for res_id in res_ids:
                values_all[res_id]['reply_to'] = self.reply_to
        return values_all
