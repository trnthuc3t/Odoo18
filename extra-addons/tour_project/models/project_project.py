from odoo import models, fields, api
class Project(models.Model):
    _inherit = 'project.project'

    order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sale Order',
        help='The sale order related to this project.',
        store=True,
        index=True
    )
    sale_tag_ids = fields.Many2many(
        comodel_name='crm.tag',
        string='Sale Tags',
        related='order_id.tag_ids',
        readonly=True,
    )

    def cron_update_order_links(self):
        """A cron method to update the order_id field for projects based on existing sale orders."""
        projects = self.search([('order_id', '=', False)])
        for project in projects:
            sale_order = self.env['sale.order'].search([('project_id', '=', project.id)], limit=1)
            if sale_order:
                project.order_id = sale_order.id