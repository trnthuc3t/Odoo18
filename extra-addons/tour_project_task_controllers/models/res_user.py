from odoo import models, fields, _, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    show_tasks = fields.Boolean(
        string="Show Hide Tasks",
        default=False,
        help="When enabled, shows all tasks instead of only tasks assigned to the current user"
    )