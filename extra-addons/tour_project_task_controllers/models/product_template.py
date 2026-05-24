from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    task_template_ids = fields.Many2many(
        comodel_name='tour.task.template',
        relation='task_template_product_template_rel',
        column1='product_template_id',
        column2='template_id',
        string='Task Templates',
        help='Task templates executed for this product when Sale Order is converted to Project.',
    )
