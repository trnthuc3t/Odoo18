from odoo import _, fields, models
from odoo.exceptions import UserError


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

    def _raise_customer_care_edit_warning(self):
        if self.env.user.has_group('tour_project_task_controllers.group_tour_customer_care'):
            raise UserError(_("Customer Care cannot edit Product. Please contact an administrator."))

    def write(self, vals):
        self._raise_customer_care_edit_warning()
        return super().write(vals)

    def unlink(self):
        self._raise_customer_care_edit_warning()
        return super().unlink()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _raise_customer_care_edit_warning(self):
        if self.env.user.has_group('tour_project_task_controllers.group_tour_customer_care'):
            raise UserError(_("Customer Care cannot edit Product. Please contact an administrator."))

    def write(self, vals):
        self._raise_customer_care_edit_warning()
        return super().write(vals)

    def unlink(self):
        self._raise_customer_care_edit_warning()
        return super().unlink()
