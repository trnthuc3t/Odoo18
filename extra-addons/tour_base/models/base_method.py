from odoo import api, models

class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def get_environment(self):
        if len(self) > 1:
            raise ValueError("Expected singleton or no record: %s" % self)
        return self.env['ir.config_parameter'].sudo().get_param(
            'web.base.env', default='local'
        )
