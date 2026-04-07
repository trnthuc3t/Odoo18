from odoo import models, fields, api
import json


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    crm_lead_line_ids = fields.One2many(
        comodel_name='crm.lead.line',
        inverse_name='crm_lead_id',
        string='CRM Lead Lines',
    )
    is_done_order = fields.Boolean(
        string='Is Done Order',
        default=False,
    )
    transaction_info = fields.Text(
        string='Transaction Info',
        help='Information about transactions related to this lead.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    crm_product_ids = fields.Many2many(
        comodel_name='product.template',
        string='Products',
        relation='crm_lead_product_rel',
        help='Products associated with this CRM lead.',
    )

    @api.constrains('crm_product_ids')
    def _update_crm_lead_lines_from_products(self):
        for record in self:
            existing_product_tmpl_ids = record.crm_lead_line_ids.mapped('product_template_id').ids
            for product in record.crm_product_ids:
                if product.id not in existing_product_tmpl_ids:
                    self.env['crm.lead.line'].create({
                        'crm_lead_id': record.id,
                        'product_template_id': product.id,
                        'product_id': product.product_variant_id[0].id if product.product_variant_id else False,
                        'quantity': 1,
                        'price_unit': product.list_price,
                        'tax_id': False,
                    })

    @api.constrains('crm_lead_line_ids')
    def _add_tags_from_lines(self):
        for record in self:
            product_tags = record.crm_lead_line_ids.mapped(
                'product_template_id.product_tag_ids'
            )
            record.tag_ids = [(4, tag.id) for tag in product_tags]

    def _prepare_opportunity_quotation_context(self):
        ctx = super()._prepare_opportunity_quotation_context()
        if self.crm_lead_line_ids:
            order_line_vals = []
            for line in self.crm_lead_line_ids:
                order_line_vals.append((0, 0, {
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'price_unit': line.price_unit,
                    'tax_id': [(6, 0, [line.tax_id.id])] if line.tax_id else []
                }))
            ctx['default_order_line'] = order_line_vals
        return ctx
    
    def action_create_lead_lines(self, payload):
        """payload: {
            'product_tmpl_name': str,
            'product_tmpl_sku': str,
            'product_tmpl_id': Integer,
            'quantity': float,
            'price_unit': float,
        }"""
        self.ensure_one()
        for line_data in payload:
            if payload.get('product_tmpl_name') or payload.get('product_tmpl_sku') or payload.get('product_tmpl_id'):
                product_template_id = self.pick_product_id_from_name(payload)
                if not product_template_id:
                    continue
                line_data['product_template_id'] = product_template_id
            self.env['crm.lead.line'].create({
                'crm_lead_id': self.id,
                'product_template_id': line_data.get('product_template_id'),
                'quantity': line_data.get('quantity', 1),
                'price_unit': line_data.get('price_unit', 0.0),
                'tax_id': False,
            })

    def pick_product_id_from_name(self, payload):
        self.ensure_one()
        if payload is None:
            return False
        if payload.product_tmpl_id:
            product_tmpl_id = self.env['product.template'].browse(payload.product_tmpl_id.id)
            if product_tmpl_id.exists():
                return product_tmpl_id.id
        elif payload.product_tmpl_name:
            product_tmpl_id = self.env['product.template'].search([('name', '=', payload.product_tmpl_name)], limit=1)
            if product_tmpl_id.exists():
                return product_tmpl_id.id if product_tmpl_id else False
        elif payload.product_tmpl_sku:
            product_tmpl_id = self.env['product.template'].search([('default_code', '=', payload.product_tmpl_sku)], limit=1)
            if product_tmpl_id.exists():
                return product_tmpl_id.id if product_tmpl_id else False
        return False
    
    def _extend_transaction_info(self, trans_info):
        if not self.transaction_info:
            self.transaction_info = ""
        self.is_done_order = True
        self.transaction_info.update(trans_info)
    
    def _action_create_quotation(self):
        pricelist_id = self.env['product.pricelist'].search([('currency_id', '=', self.currency_id.id)], limit=1).id
        order_info = {
            'partner_id': self.partner_id.id,
            'partner_invoice_id': self.partner_id.id,
            'partner_shipping_id': self.partner_id.id,
            'opportunity_id': self.id,
            'pricelist_id': pricelist_id,
            'team_id': self.team_id.id,
            'campaign_id': self.campaign_id.id,
            'medium_id': self.medium_id.id,
            'source_id': self.source_id.id,
        }
        order_details = []
        for line in self.crm_lead_line_ids:
            order_details.append((0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.price_unit,
                'tax_id': [(6, 0, [line.tax_id.id])] if line.tax_id else []
            }))
        order_info['order_line'] = order_details
        quotation = self.env['sale.order'].create(order_info)
        return quotation
    
    @api.constrains('stage_id')
    def _constrains_stage_id_crm_lead(self):
        for record in self:
            if record.stage_id and record.stage_id.name == "Won":
                if record.transaction_info:
                    transaction_info = json.loads(record.transaction_info) if record.transaction_info else {}
                    currency = transaction_info.get('currency_code')
                    if (
                        not record.order_ids
                        and record.is_done_order
                        and record.crm_lead_line_ids
                        and currency is not None
                        and record.currency_id.name
                        and record.currency_id.name.lower() == currency.lower()
                    ):
                        if not record.partner_id and record.email_from:
                            #Create partner from email if not exist
                            partner = self.env['res.partner'].sudo().search([('email', '=', record.email_from)], limit=1)
                            if not partner:
                                partner = self.env['res.partner'].sudo().create({
                                    'name': record.contact_name or record.email_from,
                                    'email': record.email_from,
                                    'user_id': record.user_id.id if record.user_id else False,
                                })
                            record.partner_id = partner.id
                        #Khởi tạo một đơn báo giá nếu chưa có
                        quotation = record._action_create_quotation()
                        record.order_ids = [(4, quotation.id)]
                        quotation.action_confirm()
                        #Create Invoice
                        invoice = quotation._create_invoices(final=True)
                        invoice.action_post()
                        #Gán trạng thái thanh toán cho hóa đơn
                        invoice.create_won_deal_invoice_payment(transaction_info)