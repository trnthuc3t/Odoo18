from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class TaskTemplate(models.Model):
    _name = "tour.task.template"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Task Template for Auto-generating Project Tasks"
    _order = "sequence, id"

    # Basic Information
    name = fields.Char(string="Template Name", required=True)
    description = fields.Html(string="Description")
    is_active = fields.Boolean(string="Is Active", default=True)
    sequence = fields.Integer(string="Sequence", default=10, help="Order of task execution")
    
    # Assignment Fields
    user_id = fields.Many2one(
        'res.users',
        string="Assigned User",
        domain=[('employee_ids', '!=', False)],
        help="Only users linked to an Employee can be selected.",
    )
    mentor = fields.Many2one('res.users', string="Mentor")
    manager_id = fields.Many2one('res.users', string="Manager")
    is_assign_salesperson = fields.Boolean(string="Assign to Salesperson", default=False)
    department_id = fields.Many2one('hr.department', string="Department")
    
    # Duration & Scheduling
    duration = fields.Float(string="Estimated Duration", required=True, default=1.0)
    duration_unit = fields.Selection([
        ('minutes', 'Minutes'), 
        ('hours', 'Hours'), 
        ('days', 'Days'),
        ('weeks', 'Weeks')
    ], string="Duration Unit", default='hours')
    duration_in_minutes = fields.Float(
        string="Duration in Minutes", 
        compute='_compute_duration_in_minutes', 
        store=True
    )
    
    # Start Time Configuration
    start_offset = fields.Float(string="Start Offset", default=0, help="Delay before starting this task")
    start_offset_unit = fields.Selection([
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days')
    ], string="Offset Unit", default='hours')
    start_offset_in_minutes = fields.Float(
        string="Start Offset in Minutes", 
        compute='_compute_start_offset_in_minutes', 
        store=True
    )
    
    # Product Linking - KEY for template selection
    product_ids = fields.Many2many(
        'product.product',
        'task_template_product_rel',
        'template_id',
        'product_id',
        string="Linked Products (Specific Variants)",
        help="This template will be used when any of these products are in the invoice"
    )
    product_template_ids = fields.Many2many(
        'product.template',
        'task_template_product_template_rel', 
        'template_id',
        'product_template_id',
        string="Linked Product Templates",
        help="This template will be used when any product from these templates are in the invoice"
    )
    
    # Task Dependencies
    depends_on_ids = fields.Many2many(
        'tour.task.template',
        'task_template_dependency_rel',
        'task_id',
        'depends_on_id',
        string="Depends On",
        help="This task will start only after these tasks are completed"
    )
    blocking_ids = fields.Many2many(
        'tour.task.template',
        'task_template_dependency_rel',
        'depends_on_id',
        'task_id',
        string="Blocks",
        help="These tasks depend on this task"
    )
    
    # Priority & Type
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string="Priority", default='1')
    
    task_type = fields.Selection([
        ('preparation', 'Preparation'),
        ('execution', 'Execution'),
        ('verification', 'Verification'),
        ('completion', 'Completion')
    ], string="Task Type", default='execution')
    
    # Categorization
    tags = fields.Many2many('project.tags', string="Task Tags")
    task_categories = fields.Many2many('tour.task.template.tag', string="Service Categories")
    
    # Project Settings
    stage_id = fields.Many2one(
        'project.task.type',
        string="Initial Stage",
        default=lambda self: self.env['project.task.type'].search([('name', '=', 'New')], limit=1).id
    )
    
    # Company
    company_id = fields.Many2one(
        'res.company', 
        string="Company", 
        default=lambda self: self.env.company
    )
    is_export_invoice_vat_template = fields.Boolean(
        string="Use for Export Invoice VAT Tasks",
        default=False,
        help="This template will be used for tasks related to export invoice VAT processing"
    )

    is_no_duplicate_task = fields.Boolean(
        string="No Duplicate Tasks",
        default=False,
        help="If checked, only one task from this template will be created per project"
    )

    @api.onchange('user_id')
    def _onchange_user_for_department(self):
        """Auto-set department based on selected user"""
        for record in self:
            if record.user_id:
                employee = self.env['hr.employee'].search([('user_id', '=', record.user_id.id)], limit=1)
                record.department_id = employee.department_id.id if employee else False
            else:
                record.department_id = False

    @api.depends('duration', 'duration_unit')
    def _compute_duration_in_minutes(self):
        """Convert duration to minutes for consistent calculation"""
        for record in self:
            if record.duration <= 0:
                raise ValidationError(_("Duration must be a positive number."))
            
            if record.start_offset < 0:
                raise ValidationError(_("Start offset cannot be negative. Please use a positive value."))
            
            if record.duration_unit == 'minutes':
                record.duration_in_minutes = record.duration
            elif record.duration_unit == 'hours':
                record.duration_in_minutes = record.duration * 60
            elif record.duration_unit == 'days':
                record.duration_in_minutes = record.duration * 60 * 24
            elif record.duration_unit == 'weeks':
                record.duration_in_minutes = record.duration * 60 * 24 * 7
                
    @api.depends('start_offset', 'start_offset_unit')
    def _compute_start_offset_in_minutes(self):
        """Convert start offset to minutes for consistent calculation"""
        for record in self:
            if record.start_offset < 0:
                raise ValidationError(_("Start offset must be zero or a positive number."))
            
            if record.start_offset_unit == 'minutes':
                record.start_offset_in_minutes = record.start_offset
            elif record.start_offset_unit == 'hours':
                record.start_offset_in_minutes = record.start_offset * 60
            elif record.start_offset_unit == 'days':
                record.start_offset_in_minutes = record.start_offset * 60 * 24
    
    @api.constrains('product_ids', 'product_template_ids')
    def _check_product_link(self):
        """At least one product or product template must be selected"""
        for record in self:
            if not record.product_ids and not record.product_template_ids and not record.is_export_invoice_vat_template:
                raise ValidationError(
                    _("Template '%s' must be linked to at least one Product or Product Template!") % record.name
                )
    
    @api.constrains('depends_on_ids')
    def _check_circular_dependency(self):
        """Prevent circular dependencies in task templates"""
        for record in self:
            if record in record.depends_on_ids:
                raise ValidationError(_("A task cannot depend on itself."))
            
            # Check for circular dependencies using DFS
            visited = set()
            def check_circular(template):
                if template.id in visited:
                    return True
                visited.add(template.id)
                for dep in template.depends_on_ids:
                    if check_circular(dep):
                        return True
                visited.remove(template.id)
                return False
            
            if check_circular(record):
                raise ValidationError(_("Circular dependency detected in task templates."))

    def get_task_from_product_id(self, product_id):
        """
        Get task templates associated with a product
        Priority: product.product (specific variant) > product.template
        
        Args:
            product_id: ID of product.product
            
        Returns:
            recordset of tour.task.template
        """
        if not product_id:
            return self.env['tour.task.template']
        
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            _logger.warning(f"Product with ID {product_id} not found")
            return self.env['tour.task.template']
        
        # Priority 1: Search for templates with this product in product_ids
        tasks = self.search([
            ('product_ids', 'in', [product_id]),
            ('is_active', '=', True)
        ], order='sequence, id')
        
        # Priority 2: Search by product_template_ids (fallback)
        if not tasks:
            tasks = self.search([
                ('product_template_ids', 'in', [product.product_tmpl_id.id]),
                ('is_active', '=', True)
            ], order='sequence, id')
        
        _logger.info(f"Found {len(tasks)} task templates for product {product.name}")
        return tasks
    
    def get_sorted_by_dependencies(self):
        """
        Sort task templates by their dependencies using topological sort
        Returns tasks in execution order (dependencies first)
        
        Returns:
            recordset of tour.task.template in dependency order
        """
        sorted_tasks = []
        visited = set()
        temp_mark = set()
        
        def visit(task):
            if task.id in temp_mark:
                raise ValidationError(_("Circular dependency detected in task templates"))
            if task.id in visited:
                return
            
            temp_mark.add(task.id)
            # Visit dependencies first
            for dep in task.depends_on_ids:
                visit(dep)
            temp_mark.remove(task.id)
            visited.add(task.id)
            sorted_tasks.append(task)
        
        for task in self:
            if task.id not in visited:
                visit(task)
        
        return self.env['tour.task.template'].browse([t.id for t in sorted_tasks])


class TaskTemplateTag(models.Model):
    _name = "tour.task.template.tag"
    _description = "Task Template Tag"
    _order = "sequence, id"

    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Tag Name", required=True)
    color = fields.Integer(string="Color Index", default=0)
