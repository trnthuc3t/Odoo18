from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_combo_multiple_choice = fields.Boolean(
        string='Is Combo Multiple Choice',
        default=True,
        help='Indicates if the product is a combo with multiple choice options.'
    )
    is_day_tour = fields.Boolean(
        string='Is Day Tour',
        default=False,
        help='Indicates if the combo is a day tour.'
    )

    def get_single_product_variant(self):

        res = super().get_single_product_variant()
        if res.get('is_combo'):
            product_template = self.env['product.product'].browse(res.get('product_id')).product_tmpl_id
            if product_template.is_day_tour:
                res.update({'is_day_tour': True})
            elif product_template.is_combo_multiple_choice:
                res.update({'is_combo_multiple_choice': True})
        return res