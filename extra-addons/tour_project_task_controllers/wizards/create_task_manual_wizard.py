from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class CreateTaskManualWizard(models.TransientModel):
    _name = "create.task.manual.wizard"
    _description = "Manual Task Creation Wizard"

    # Basic Information
    name = fields.Char(string="Template Name", required=True)
    description = fields.Html(string="Description")
    
    # Assignment Fields
    user_id = fields.Many2one('res.users', string="Assigned User")
    mentor_id = fields.Many2one('res.users', string="Mentor")
    manager_id = fields.Many2one('res.users', string="Manager")
    is_assign_to_me = fields.Boolean(string="Assign to Me", default=False)
    department_id = fields.Many2one('hr.department', string="Department")

    start_date = fields.Datetime(string="Start Date", default=fields.Datetime.now)
    deadline = fields.Datetime(string="Deadline")
    order_id = fields.Many2one('sale.order', string="Related Sale Order", required=True)

    tag_ids = fields.Many2many('project.tags', string="Tags")

    @api.constrains('deadline', 'start_date')
    def _check_dates(self):
        for record in self:
            if record.deadline and record.start_date and record.deadline < record.start_date:
                raise ValidationError(_("Deadline cannot be earlier than Start Date."))

    @api.onchange('is_assign_to_me')
    def _onchange_is_assign_to_me(self):
        if self.is_assign_to_me:
            self.user_id = self.env.user.id
        else:
            self.user_id = False

    @api.onchange('user_id')
    def _onchange_user_id(self):
        """Auto-fill department when user is selected"""
        if self.user_id and self.user_id.employee_ids:
            self.department_id = self.user_id.employee_ids[0].department_id
        else:
            self.department_id = False
    
    def action_create_task(self):
        if not self.order_id.project_id:
            raise ValidationError(_("The related Sale Order must have an associated Project to create tasks."))
        task_vals = {
            'name': f"[{self.order_id.name}] {self.name}",
            'description': self.description,
            'project_id': self.order_id.project_id.id,
            'user_ids': [(6, 0, [self.user_id.id] if self.user_id else [])],
            'mentor_id': self.mentor_id.id if self.mentor_id else False,
            'manager_id': self.manager_id.id if self.manager_id else False,
            'date_start': self.start_date,
            'date_deadline': self.deadline,
            'tag_ids': [(6, 0, self.tag_ids.ids)] if self.tag_ids else False,
        }
        
        self.env['project.task'].create(task_vals)
        return {
            'effect': {
                'fadeout': 'slow',
                'message': "Task Created Successfully",
                    'type': 'rainbow_man',
            }
        }
