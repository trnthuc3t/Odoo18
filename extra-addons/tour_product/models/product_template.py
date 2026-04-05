from odoo import models, fields, api
from datetime import timedelta
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sale_tag_ids = fields.Many2many(
        comodel_name='crm.tag',
        string='Sale Tags')
    
    is_update = fields.Boolean(string="Is Update", default=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['is_update'] = True
        return super().create(vals_list)

    def write(self, vals):
        if 'attribute_line_ids' in vals:
            vals['is_update'] = True
        return super().write(vals)
    
    def cron_push_product_update_to_lark_base(self):
        """Cron job to push product updates to LarkBase."""
        products_to_update = self.search([('is_update', '=', True)])
        LarkWebHook = self.env['lark.web.hook'].sudo()
        lark_job = LarkWebHook.get_lark_job_from_short_name('lark_base_product_update')
        if not lark_job:
            return
        product_info = []
        product_pending_ids = []
        for product in products_to_update:
            variants = self.env['product.product'].search([('product_tmpl_id', '=', product.id)])
            variant_info = []
            if product.type == 'combo':
                product.is_update = False
                continue  # Skip combo products
            if product.write_date < (fields.Datetime.now() - timedelta(minutes=10)):
                product_pending_ids.append(product)
                continue
            
            for variant in variants:
                variant_info.append({
                    "id": variant.id,
                    "name": variant.name,
                    "default_code": variant.default_code,
                    "combination": variant.product_template_variant_value_ids.mapped('display_name'),
                    "cost_price": variant.standard_price,
                    "no_variant": True if not variant.product_template_variant_value_ids else False,
                })
            product_info.append({
                "id": product.id,
                "name": product.name,
                "default_code": product.default_code,
                "variants": variant_info,
                "cost_price": product.standard_price,
                "sale_price": product.list_price,
            })

        if not product_info:
            return
        payload = {
            "products": product_info
        }
        response = lark_job.send_hook_request(payload)
        if response:
            products_to_update.write({'is_update': False})
        if product_pending_ids:
            for prod in product_pending_ids:
                prod.is_update = True