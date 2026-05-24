from odoo import models, fields, api, _
from datetime import timedelta

class ProjectProjec(models.Model):
    _inherit = 'project.project'

    show_tasks = fields.Boolean(
        string="Show Hide Tasks",
        help="When enabled, shows all tasks instead of only tasks assigned to the current user",
        compute='_compute_show_tasks',
        store=False,
    )
    task_user_ids = fields.Many2many(
        'project.task',
        compute='_compute_task_user_ids',
        string='My Tasks',
        store=False,
    )

    def _compute_show_tasks(self):
        for project in self:
            project.show_tasks = self.env.user.show_tasks

    def show_hide_tasks(self):
        if not self.env.user.show_tasks:
            self.env.user.show_tasks = True
        else:
            self.env.user.show_tasks = False

    @api.depends('show_tasks')
    def _compute_task_user_ids(self):
        for project in self:
            all_tasks = self.env['project.task'].search([('project_id', '=', project.id)])
            if project.show_tasks:
                project.task_user_ids = all_tasks
            else:
                project.task_user_ids = all_tasks.filtered(lambda t: self.env.user in t.user_ids)

    def action_view_tasks(self):
        action = super().action_view_tasks()
        action['context']['search_default_my_tasks'] = 1
        return action
    
class ProjectTask(models.Model):
    _inherit = 'project.task'
    
    # Mentor and Manager fields
    mentor_id = fields.Many2one(
        'res.users', 
        string="Mentor", 
        tracking=True,
        help="Mentor who guides the assigned user"
    )
    manager_id = fields.Many2one(
        'res.users', 
        string="Manager", 
        tracking=True,
        help="Manager who oversees this task"
    )
    
    # Task Dependencies
    depend_on_ids = fields.Many2many(
        'project.task',
        'project_task_dependency_rel',
        'task_id',
        'depends_on_id',
        string="Depends On",
        help="This task depends on these tasks (blocking dependencies)"
    )
    blocking_task_ids = fields.Many2many(
        'project.task',
        'project_task_dependency_rel',
        'depends_on_id',
        'task_id',
        string="Blocking Tasks",
        help="These tasks depend on this task (blocked tasks)"
    )

    stage_id = fields.Many2one('project.task.type', string='Stage', compute='_compute_stage_id',
        store=True, readonly=False, ondelete='restrict', tracking=True, index=True,
        default=lambda self: self.env['project.task.type'].search([('name', '=', 'New')], limit=1), group_expand='_read_group_stage_ids',
        domain="[('is_usable', '=', True)]")
    
    # Computed fields for dependency status
    has_dependencies = fields.Boolean(
        compute='_compute_dependency_status', 
        store=True,
        string="Has Dependencies"
    )
    dependencies_completed = fields.Boolean(
        compute='_compute_dependency_status', 
        store=True,
        string="Dependencies Completed"
    )
    can_start = fields.Boolean(
        compute='_compute_dependency_status', 
        store=True,
        string="Can Start",
        help="All dependencies are completed"
    )
    date_start = fields.Datetime(string="Start Date", tracking=True)
    
    @api.model
    def _read_group_stage_ids(self, stages, domain):
        search_domain = [('is_usable', '=', True)]
        if 'default_project_id' in self.env.context and not self._context.get('subtask_action') and 'project_kanban' in self.env.context:
            search_domain = ['|', ('project_ids', '=', self.env.context['default_project_id'])] + search_domain
        stage_ids = stages._search(search_domain, order=stages._order)
        return stages.browse(stage_ids)

    @api.constrains('stage_id')
    def  _constrains_stage_id_set_state(self):
        stage_state_map = {
            'New': '01_in_progress',
            'Processing': '02_changes_requested',
            'Ending': '1_done',
            'Approving': '03_approved',
            'Pending': '04_waiting_normal',
            'Finished': '1_done',
            'Cancelled': '1_canceled',
        }
        for rec in self:
            if rec.stage_id and rec.stage_id.name in stage_state_map:
                rec.state = stage_state_map[rec.stage_id.name]
            if rec.project_id:
                all_project_tasks = self.env['project.task'].search([('project_id', '=', rec.project_id.id)])
                task_not_finished = all_project_tasks.filtered(lambda t: t.stage_id.name not in ('Finished', 'Ending'))
                if not task_not_finished:
                    happy_ending_stage = self.env['project.project.stage'].search([('name', 'ilike', 'Happy Ending')], limit=1)
                    rec.project_id.stage_id = happy_ending_stage.id if happy_ending_stage else False


    @api.constrains('state')
    def _constrains_state_set_stage_id(self):
        state_stage_map = {
            '01_in_progress': 'New',
            '02_changes_requested': 'Processing',
            '03_approved': 'Approving',
            '04_waiting_normal': 'Pending',
            '1_done': 'Ending',
            '1_canceled': 'Cancelled',
        }
        for rec in self:
            if rec.state in state_stage_map:
                stage = self.env['project.task.type'].search([('name', '=', state_stage_map[rec.state])], limit=1)
                if not stage and rec.state == '1_done':
                    # Backward compatibility with old stage naming.
                    stage = self.env['project.task.type'].search([('name', '=', 'Finished')], limit=1)
                if stage:
                    rec.stage_id = stage

    @api.depends('depend_on_ids', 'depend_on_ids.stage_id', 'depend_on_ids.stage_id')
    def _compute_dependency_status(self):
        """Check if dependencies are completed"""
        for task in self:
            task.has_dependencies = bool(task.depend_on_ids)
            
            if task.depend_on_ids:
                # Check if all dependent tasks are in closed/folded stage
                all_completed = all(
                    dep.stage_id.name in ('Finished', 'Ending', 'Cancelled')
                    for dep in task.depend_on_ids 
                    if dep.stage_id
                )
                task.dependencies_completed = all_completed
                if all_completed and not task.stage_id.name in ('Finished', 'Ending', 'Cancelled'):
                    task.can_start = True
                    task.date_start = fields.Datetime.now()
                    if task.date_deadline < fields.Datetime.now():
                        task.date_deadline = fields.Datetime.now() + timedelta(days=1)
                else:
                    task.can_start = False
            else:
                task.dependencies_completed = True
                task.can_start = True
    
    def action_view_dependencies(self):
        """View all tasks this task depends on"""
        self.ensure_one()
        
        if not self.depend_on_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Dependencies'),
                    'message': _('This task has no dependencies.'),
                    'type': 'info',
                }
            }
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dependent Tasks'),
            'res_model': 'project.task',
            'view_mode': 'tree,form,kanban',
            'domain': [('id', 'in', self.depend_on_ids.ids)],
        }
    
    def action_view_blocking_tasks(self):
        """View all tasks that depend on this task"""
        self.ensure_one()
        
        if not self.blocking_task_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Blocked Tasks'),
                    'message': _('No tasks are waiting for this one.'),
                    'type': 'info',
                }
            }
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Blocked Tasks'),
            'res_model': 'project.task',
            'view_mode': 'tree,form,kanban',
            'domain': [('id', 'in', self.blocking_task_ids.ids)],
        }

class TaskStage(models.Model):
    _inherit = 'project.task.type'
    
    is_usable = fields.Boolean(
        string="Usable in Task Templates",
        default=False,
        help="Indicates if this stage can be selected in task templates"
    )

    @api.model
    def _ensure_default_tour_task_stages(self):
        defaults = [
            ('New', 10),
            ('Processing', 20),
            ('Ending', 30),
        ]
        for name, sequence in defaults:
            stage = self.search([('name', '=', name)], limit=1)
            if not stage:
                self.create({
                    'name': name,
                    'sequence': sequence,
                    'is_usable': True,
                    'fold': False,
                })
            else:
                vals = {}
                if not stage.is_usable:
                    vals['is_usable'] = True
                if stage.fold:
                    vals['fold'] = False
                if vals:
                    stage.write(vals)

    def init(self):
        self._ensure_default_tour_task_stages()