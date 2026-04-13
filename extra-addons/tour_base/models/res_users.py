from odoo import fields, models

class ResUsers(models.Model):
    _inherit = 'res.users'

    api_key = fields.Char(
        string='API Key',
        copy=False,
    )
