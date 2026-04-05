from odoo import models, fields, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    published_on_websites = fields.Many2many(
        comodel_name='tour.website',
        string='Published on Websites')
    