# -*- coding: utf-8 -*-

from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    detail_information = fields.Html(
        string='Detail Information',
        translate=True,
        help='Detailed information about the product, e.g. Travel Itinerary.'
    )
