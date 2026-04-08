from odoo import models

class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    def create_invoices(self):
        if len(self.sale_order_ids) > 1:
            raise ValueError("Creating advance payment invoices for multiple sales orders is not allowed.")
        if not self.sale_order_ids:
            raise ValueError("No sale order selected for creating advance payment invoice.")
        order_id = self.sale_order_ids[0]
        res = super(SaleAdvancePaymentInv, self).create_invoices()
        invoice = self.env['account.move'].browse(res.get('res_id'))
        invoice.order_id = order_id.id
        return res