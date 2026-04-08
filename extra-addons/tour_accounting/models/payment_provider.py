from odoo import models, fields, api


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    bank_account_number = fields.Char(string='Bank Account Number')
    bank_name = fields.Char(string='Bank Name')
    bank_account_holder = fields.Char(string='Bank Account Holder')
    
    def get_company_phone(self):
        self.ensure_one()
        return self.company_id.phone or 'N/A'
    
    def get_company_email(self):
        self.ensure_one()
        return self.company_id.email or 'N/A'