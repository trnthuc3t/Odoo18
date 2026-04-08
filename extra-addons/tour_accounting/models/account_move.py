from odoo import api, models, fields, _
from odoo.service.model import request


class AccountMove(models.Model):
    _inherit = 'account.move'

    acc_holder_name = fields.Char(string='Account Holder Name', related='partner_bank_id.acc_holder_name', related_sudo=True, store=True)
    order_id = fields.Many2one(string='Sales Order', comodel_name='sale.order', ondelete='set null', copy=False, index=True)
    
    def action_send_and_print(self):
        self.env['account.move.send']._check_move_constrains(self)
        payment_link_gen = self.env['payment.link.wizard'].sudo().create({
            'res_model': 'account.move',
            'res_id': self.id,
            'amount': self.amount_residual,
            'currency_id': self.currency_id.id,
            'partner_id': self.partner_id.id,
        })
        payment_link = payment_link_gen.link
        return {
            'name': _("Print & Send"),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'account.move.send.wizard' if len(self) == 1 else 'account.move.send.batch.wizard',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': self.ids,
                'default_payment_link': payment_link,
                'payment_link': payment_link,
            },
        }

    def _generate_vietqr_code_image(self, account_holder_name=None, account_number=None, bank_name=None, amount=None, info=None):
        for record in self:
            acc_holder_name = record.acc_holder_name or ''
            record._generate_vietqr_code_image_custom(acc_holder_name=acc_holder_name)

    def manual_get_order_id_from_origin(self):
        """Get sale order from origin field."""
        self.ensure_one()
        SaleOrder = self.env['sale.order']
        origin = self.invoice_origin
        if origin:
            sale_order = SaleOrder.sudo().search([('name', '=', origin)], limit=1)
            return sale_order
        return False
    
    def action_view_source_sale_orders(self):
        self.ensure_one()
        source_orders = self.order_id
        result = self.env['ir.actions.act_window']._for_xml_id('sale.action_orders')
        if len(source_orders) > 1:
            result['domain'] = [('id', 'in', source_orders.ids)]
        elif len(source_orders) == 1:
            result['views'] = [(self.env.ref('sale.view_order_form', False).id, 'form')]
            result['res_id'] = source_orders.id
        else:
            result = {'type': 'ir.actions.act_window_close'}
        return result

    def create_won_deal_invoice_payment(self, transaction_info):
        """Create payment for the invoice based on the transaction info from CRM lead."""
        self.ensure_one()
        payment_gateway = transaction_info.get('payment_gateway')
        payment_amount = transaction_info.get('amount')
        journal = self.env['account.journal'].search([('name', 'ilike', payment_gateway)], limit=1)
        journal_id = False
        if journal:
            journal_id = journal.id
        if journal_id and payment_amount:
            self.env['account.payment.register'].sudo().with_context(active_model='account.move', active_ids=[self.id]).create({
                'journal_id': journal_id,
                'amount': float(payment_amount),
                'currency_id': self.currency_id.id,
                'communication': self.name,
                'payment_date': fields.Date.today()
            })._create_payments()

    def action_generate_payment_link(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate a Payment Link',
            'res_model': 'payment.link.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('payment.payment_link_wizard_view_form').id,
            'target': 'new',
            'binding_model_id': self.env.ref('account.model_account_move').id,
            'binding_view_types': 'form',
        }

    def _get_invoice_lines_to_show(self):
        """Trả về invoice lines đã lọc bỏ các combo item thuộc combo multiple choice.
        Dùng cho template report/portal để ẩn detail sản phẩm trong combo mc khỏi khách hàng.
        """
        lines = self.invoice_line_ids.sorted(
            key=lambda l: (-l.sequence, l.date, l.move_name, -l.id), reverse=True
        )
        return lines.filtered(
            lambda l: not any(
                sol.combo_item_id
                and sol.linked_line_id.product_template_id.is_combo_multiple_choice
                for sol in l.sale_line_ids
            )
        )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    is_combo_mc_label = fields.Boolean(
        compute='_compute_combo_mc_flags',
        store=False,
        string='Is Combo MC Label',
    )
    combo_mc_subtotal = fields.Float(
        compute='_compute_combo_mc_flags',
        store=False,
        string='Combo MC Subtotal',
    )

    @api.depends('sale_line_ids', 'display_type')
    def _compute_combo_mc_flags(self):
        """Tính 2 flag cho invoice line thuộc combo multiple choice:
        - is_combo_mc_label: True nếu là line_note đại diện tên combo mc
        - combo_mc_subtotal: tổng price_subtotal của các combo item bị ẩn
        """
        for line in self:
            is_label = (
                line.display_type == 'line_note'
                and any(
                    sol.display_type == 'line_note'
                    and sol.linked_line_id
                    and sol.linked_line_id.product_template_id.is_combo_multiple_choice
                    for sol in line.sale_line_ids
                )
            )
            line.is_combo_mc_label = is_label
            if is_label:
                sale_note_sol = next((
                    sol for sol in line.sale_line_ids
                    if sol.display_type == 'line_note'
                    and sol.linked_line_id
                    and sol.linked_line_id.product_template_id.is_combo_multiple_choice
                ), False)
                if sale_note_sol:
                    combo_parent_sol = sale_note_sol.linked_line_id
                    combo_item_inv_lines = line.move_id.invoice_line_ids.filtered(
                        lambda l: any(
                            sol.combo_item_id and sol.linked_line_id == combo_parent_sol
                            for sol in l.sale_line_ids
                        )
                    )
                    line.combo_mc_subtotal = sum(combo_item_inv_lines.mapped('price_subtotal'))
                else:
                    line.combo_mc_subtotal = 0.0
            else:
                line.combo_mc_subtotal = 0.0