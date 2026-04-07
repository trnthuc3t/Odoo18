from odoo import models, fields, api


class CrmLeadLine(models.Model):
    _name = 'crm.lead.line'
    _description = 'CRM Lead Line'
    _order = 'id desc'

    crm_lead_id = fields.Many2one(
        comodel_name='crm.lead',
        string='CRM Lead',
    )
    product_template_id = fields.Many2one(
        comodel_name='product.template',
        string='Product Template',
        domain="[('sale_ok', '=', True)]"
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        domain="[('sale_ok', '=', True), ('product_tmpl_id', '=', product_template_id)]",
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
    )
    price_unit = fields.Float(
        string='Unit Price',
        default=0.0,
    )
    subtotal = fields.Float(
        string='Subtotal',
        default=0.0,
    )
    tax_id = fields.Many2one(
        comodel_name='account.tax',
        string='Taxes',
        domain=[('type_tax_use', 'in', ('sale', 'all'))],
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='crm_lead_id.currency_id',
        readonly=True,
        domain=[('active', '=', True)],
        store=True,
    )

    @api.onchange('product_template_id', 'product_id', 'quantity', 'price_unit', 'tax_id')
    def _onchange_calculate_subtotal(self):
        for record in self:
            subtotal = record.quantity * record.price_unit
            if record.tax_id:
                taxes = record.tax_id.compute_all(
                    subtotal,
                    currency=record.crm_lead_id.company_id.currency_id,
                    quantity=1.0,
                    product=record.product_id,
                    partner=record.crm_lead_id.partner_id,
                )
                subtotal = taxes['total_included']
            if record.subtotal != subtotal:
                record.subtotal = subtotal

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill price_unit when product_id changes"""
        if self.product_id:
            # Get price from pricelist
            pricelist_items = self.env['product.pricelist.item'].search([
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)
            ], limit=1)
            if pricelist_items:
                pricelist = pricelist_items.pricelist_id
                price = pricelist._get_product_price(
                    self.product_id,
                    self.quantity or 1.0,
                    partner=False,
                    date=fields.Date.today(),
                    uom_id=self.product_id.uom_id
                )
                self.price_unit = price
            else:
                # Fallback to list_price
                self.price_unit = self.product_id.list_price
            
            # Set default quantity if not set
            if not self.quantity:
                self.quantity = 1.0
                