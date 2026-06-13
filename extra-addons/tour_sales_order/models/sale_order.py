from odoo import models, fields, api, _
from odoo.exceptions import UserError
from collections import defaultdict

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    project_stage_id = fields.Many2one(
        comodel_name='project.project.stage',
        related='project_id.stage_id',
        string='Project Stage',
        store=True,
        readonly=True,
    )

    @api.constrains('order_line')
    def _constraints_line_update_tags(self):
        for order in self:
            if order.order_line and order.order_line.mapped('product_template_id.sale_tag_ids'):
                tags = order.order_line.mapped('product_template_id.sale_tag_ids')
                order.tag_ids = [(6, 0, tags.ids)]
            else:
                order.tag_ids = [(5, 0, 0)]

    def action_cancel(self):
        """ Cancel SO after showing the cancel wizard when needed. (cfr :meth:`_show_cancel_wizard`)

        For post-cancel operations, please only override :meth:`_action_cancel`.

        note: self.ensure_one() if the wizard is shown.
        """
        if any(order.locked for order in self):
            raise UserError(_("You cannot cancel a locked order. Please unlock it first."))
        # cancel_warning = self._show_cancel_wizard()
        # if cancel_warning:
        #     self.ensure_one()
        #     template_id = self.env['ir.model.data']._xmlid_to_res_id(
        #         'sale.mail_template_sale_cancellation', raise_if_not_found=False
        #     )
        #     lang = self.env.context.get('lang')
        #     template = self.env['mail.template'].browse(template_id)
        #     if template.lang:
        #         lang = template._render_lang(self.ids)[self.id]
        #     ctx = {
        #         'default_template_id': template_id,
        #         'default_order_id': self.id,
        #         'mark_so_as_canceled': True,
        #         'default_email_layout_xmlid': "mail.mail_notification_layout_with_responsible_signature",
        #         'model_description': self.with_context(lang=lang).type_name,
        #     }
        #     return {
        #         'name': _('Cancel %s', self.type_name),
        #         'view_mode': 'form',
        #         'res_model': 'sale.order.cancel',
        #         'view_id': self.env.ref('sale.sale_order_cancel_view_form').id,
        #         'type': 'ir.actions.act_window',
        #         'context': ctx,
        #         'target': 'new'
        #     }
        # else:
        return self._action_cancel()

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            order._tour_auto_create_purchase_flow()
        return res

    def _tour_get_purchase_seller(self, line):
        self.ensure_one()
        product = line.product_id.with_company(self.company_id)
        return product._select_seller(
            quantity=line.product_uom_qty,
            uom_id=line.product_uom,
            date=self.date_order.date() if self.date_order else fields.Date.context_today(self),
        )

    def _tour_auto_create_purchase_flow(self):
        self.ensure_one()
        if 'purchase.order' not in self.env:
            return
        if self.state not in ('sale', 'done'):
            return

        lines_by_vendor_currency = defaultdict(list)
        purchasable_lines = self.order_line.filtered(
            lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0
        )
        for line in purchasable_lines:
            seller = self._tour_get_purchase_seller(line)
            if not seller:
                continue
            partner = seller.partner_id.commercial_partner_id
            currency = seller.currency_id or self.company_id.currency_id
            lines_by_vendor_currency[(partner.id, currency.id)].append((line, seller))

        if not lines_by_vendor_currency:
            return

        PurchaseOrder = self.env['purchase.order'].sudo()
        existing_pos = PurchaseOrder.search([
            ('state', '!=', 'cancel'),
            ('origin', '=', self.name),
            ('company_id', '=', self.company_id.id),
            ('partner_id', 'in', [key[0] for key in lines_by_vendor_currency.keys()]),
        ])
        existing_keys = {(po.partner_id.commercial_partner_id.id, po.currency_id.id) for po in existing_pos}

        for (partner_id, currency_id), line_sellers in lines_by_vendor_currency.items():
            if (partner_id, currency_id) in existing_keys:
                continue

            partner = self.env['res.partner'].browse(partner_id)
            currency = self.env['res.currency'].browse(currency_id)

            po_line_vals = []
            for line, seller in line_sellers:
                product = line.product_id.with_company(self.company_id)
                taxes = product.supplier_taxes_id.filtered(lambda t: t.company_id == self.company_id)
                price_unit = seller.price
                if seller.currency_id and seller.currency_id != currency:
                    price_unit = seller.currency_id._convert(
                        from_amount=price_unit,
                        to_currency=currency,
                        company=self.company_id,
                        date=self.date_order.date() if self.date_order else fields.Date.context_today(self),
                    )

                po_line_vals.append((0, 0, {
                    'name': line.name or product.display_name,
                    'product_id': product.id,
                    'product_qty': line.product_uom_qty,
                    'product_uom': line.product_uom.id,
                    'date_planned': fields.Datetime.now(),
                    'price_unit': price_unit,
                    'taxes_id': [(6, 0, taxes.ids)],
                }))

            if not po_line_vals:
                continue

            po_vals = {
                'partner_id': partner.id,
                'origin': self.name,
                'company_id': self.company_id.id,
                'currency_id': currency.id,
                'date_order': fields.Datetime.now(),
                'order_line': po_line_vals,
            }
            if partner.property_supplier_payment_term_id:
                po_vals['payment_term_id'] = partner.property_supplier_payment_term_id.id

            po = PurchaseOrder.create(po_vals)
            po.button_confirm()

            create_bill_method = getattr(po, 'action_create_invoice', False) or getattr(po, '_create_invoices', False)
            if create_bill_method:
                create_bill_method()

            existing_keys.add((partner_id, currency_id))

    def _get_order_lines_to_report(self):
        """Override để ẩn các dòng sản phẩm con trong combo multiple choice trên portal/PDF.

        Với combo thường: giữ nguyên hành vi hiển thị đầy đủ các item.
        Với combo multiple choice (is_combo_multiple_choice=True): chỉ hiển thị
        dòng combo cha và dòng section (tiêu đề nhóm), ẩn các dòng sản phẩm cụ thể
        để khách hàng không thấy chi tiết bên trong combo.
        """
        lines = super()._get_order_lines_to_report()
        return lines.filtered(lambda l: not (
            l.combo_item_id
            and l.linked_line_id
            and getattr(l.linked_line_id.product_template_id, 'is_combo_multiple_choice', False)
        ))
