# -*- coding: utf-8 -*-

from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    detail_information = fields.Html(
        string='Detail Information',
        translate=True,
        help='Detailed information about the product, e.g. Travel Itinerary.'
    )

    tour_duration = fields.Char(
        string='Tour Duration',
        help='Duration text shown on website, for example: 3 Ngay 2 Dem.'
    )

    tour_location_address = fields.Char(
        string='Tour Location Address',
        help='Display address for this tour on website.'
    )

    tour_location_map_url = fields.Char(
        string='Tour Location Map URL',
        help='Google Maps URL used to open or preview tour location.'
    )
