from odoo import _
from odoo.exceptions import AccessError
from odoo import models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def check_access_rights(self, operation, raise_exception=True):
        if self.env.user.has_group('tour_project_task_controllers.group_tour_coordinator'):
            if raise_exception:
                raise AccessError(_("Coordinator is not allowed to access Purchase."))
            return False
        return super().check_access_rights(operation, raise_exception=raise_exception)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def check_access_rights(self, operation, raise_exception=True):
        if self.env.user.has_group('tour_project_task_controllers.group_tour_coordinator'):
            if raise_exception:
                raise AccessError(_("Coordinator is not allowed to access Purchase."))
            return False
        return super().check_access_rights(operation, raise_exception=raise_exception)
