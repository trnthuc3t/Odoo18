from odoo import models, fields, api, _
from odoo.exceptions import UserError

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
