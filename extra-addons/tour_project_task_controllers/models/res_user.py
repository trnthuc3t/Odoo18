from odoo import models, fields, _, api
from odoo.exceptions import ValidationError


TOUR_ROLE_GROUP_XMLIDS = (
    'tour_project_task_controllers.group_tour_coordinator',
    'tour_project_task_controllers.group_tour_accountant',
    'tour_project_task_controllers.group_tour_customer_care',
)


class ResUsers(models.Model):
    _inherit = 'res.users'

    show_tasks = fields.Boolean(
        string="Show Hide Tasks",
        default=False,
        help="When enabled, shows all tasks instead of only tasks assigned to the current user"
    )

    def _enforce_tour_role_group_restrictions(self):
        tour_role_groups = self._get_tour_role_groups()
        for user in self:
            user_tour_roles = user.groups_id & tour_role_groups
            if len(user_tour_roles) > 1:
                raise ValidationError(_("A user can only have one Tour Role."))

        coordinator_group = self.env.ref(
            'tour_project_task_controllers.group_tour_coordinator',
            raise_if_not_found=False,
        )
        if not coordinator_group:
            return

        purchase_group_ids = []
        for xmlid in (
            'purchase.group_purchase_user',
            'purchase.group_purchase_manager',
        ):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                purchase_group_ids.append(group.id)

        if not purchase_group_ids:
            return

        for user in self:
            if coordinator_group in user.groups_id:
                groups_to_remove = user.groups_id.filtered(lambda g: g.id in purchase_group_ids)
                if groups_to_remove:
                    user.with_context(skip_tour_role_restrictions=True).sudo().write({
                        'groups_id': [(3, group.id) for group in groups_to_remove]
                    })

    def _get_tour_role_groups(self):
        groups = self.env['res.groups']
        for xmlid in TOUR_ROLE_GROUP_XMLIDS:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups |= group
        return groups

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._enforce_tour_role_group_restrictions()
        return users

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('skip_tour_role_restrictions'):
            self._enforce_tour_role_group_restrictions()
        return result
