# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    has_travel_itinerary = fields.Boolean(
        string='Has Travel Itinerary',
        compute='_compute_has_travel_itinerary',
        store=False,
    )

    travel_itinerary_display = fields.Html(
        string='Travel Itinerary',
        compute='_compute_travel_itinerary_display',
        store=False,
    )

    @api.depends('product_id', 'product_id.product_tmpl_id', 'product_id.product_tmpl_id.detail_information')
    def _compute_has_travel_itinerary(self):
        """Compute if product has travel itinerary"""
        for line in self:
            # Check detail_information on the product template
            # Must access via product_tmpl_id since detail_information is on product.template
            info = line.product_id.product_tmpl_id.detail_information if line.product_id else False
            has_info = bool(info) and len(str(info).strip()) > 0
            line.has_travel_itinerary = has_info
            print(f"DEBUG: Line ID {line.id} - Product {line.product_id.name if line.product_id else 'None'} - Info Len: {len(str(info)) if info else 0} - Result: {has_info}")

    @api.depends('product_id')
    def _compute_travel_itinerary_display(self):
        """Compute travel itinerary display"""
        for line in self:
            line.travel_itinerary_display = False
            # TODO: Implement logic để hiển thị travel itinerary

    def action_view_detail_information(self):
        """Action to view product detail information"""
        self.ensure_one()
        if not self.product_id:
            return
            
        view_id = self.env.ref('tour_sales_order.view_product_template_detail_popup').id
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Detail Information',
            'res_model': 'product.template',
            'view_mode': 'form',
            'view_id': view_id,
            'res_id': self.product_id.product_tmpl_id.id,
            'target': 'new',
            'flags': {'mode': 'readonly'},
        }

