from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ProductCombo(models.Model):
    _inherit = 'product.combo'

    is_multiple_choice = fields.Boolean(
        string='Is Multiple Choice Combo',
        default=True,
        help='Indicates if the combo allows multiple choice options.'
    )
    is_day_tour = fields.Boolean(
        string='Is Day Tour',
        default=False,
        help='Indicates if the combo is a day tour.'
    )
    is_car_service = fields.Boolean(
        string='Is Car Service',
        default=False,
        help='Indicates if this combo choice is for car service selection.'
    )

    @api.constrains('combo_item_ids')
    def _check_combo_item_ids_no_duplicates(self):
        for combo in self:
            if combo.is_day_tour:
                continue 
            if len(combo.combo_item_ids.mapped('product_id')) < len(combo.combo_item_ids):
                raise ValidationError(_("A combo choice can't contain duplicate products."))



class ProductComboItem(models.Model):
    _inherit = 'product.combo.item'

    fixed_price = fields.Monetary(
        string='Fixed Price',
        help='Fixed price for this combo item when selected in a multiple choice combo.'
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        help='Quantity of the product in this combo item.'
    )
    min_quantity = fields.Integer(
        string='Minimum Quantity',
        default=1,
        help='Minimum quantity required for this combo item in a multiple choice combo.'
    )
    max_quantity = fields.Integer(
        string='Maximum Quantity',
        default=0,
        help='Maximum quantity allowed for this combo item in a multiple choice combo. 0 means no limit.'
    )
    shared_cost_enabled = fields.Boolean(
        string='Shared Cost Enabled',
        help='If enabled, the cost of this combo item will be shared among all selected items in a multiple choice combo.'
    )
