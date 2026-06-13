from odoo import models, fields, _, api
from datetime import timedelta
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    task_ids = fields.One2many('project.task', compute='_compute_task_ids', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_ids', string='Task Count')
    is_missing_info = fields.Boolean(
        string="Is Missing Info",
        default=False,
        help="Indicates if the sale order is missing information required for task generation",
        copy=False
    )
    is_missing_info_clicked = fields.Boolean(
        string="Is Missing Info Clicked",
        default=False,
        help="Indicates if the user has marked this sale order as missing information",
        copy=False
    )
    is_export_vat = fields.Boolean(
        string="Is Export VAT",
        default=False,
        help="Indicates if the sale order is subject to export VAT",
        copy=False
    )
    show_tasks = fields.Boolean(
        string="Show Hide Tasks",
        help="When enabled, shows all tasks instead of only tasks assigned to the current user",
        compute='_compute_show_tasks',
        store=False
    )
    product_template_tasks_generated = fields.Boolean(
        string='Product Template Tasks Generated',
        default=False,
        copy=False,
        help='Prevent duplicate task generation from product-linked task templates.',
    )

    def action_confirm(self):
        res = super().action_confirm()
        self._ensure_product_template_tasks_generated()
        return res

    def write(self, vals):
        res = super().write(vals)
        if 'project_id' in vals:
            self.filtered(lambda o: o.project_id and o.state in ('sale', 'done'))._ensure_product_template_tasks_generated()
        return res

    def _ensure_product_template_tasks_generated(self):
        for order in self:
            if order.product_template_tasks_generated:
                continue
            if not order.project_id:
                continue
            if order.state not in ('sale', 'done'):
                continue

            created_tasks = order._generate_tasks_from_product_templates(order.project_id)
            if created_tasks:
                order.product_template_tasks_generated = True

    def _compute_show_tasks(self):
        for order in self:
            order.show_tasks = self.env.user.show_tasks

    def show_hide_tasks(self):
        if not self.env.user.show_tasks:
            self.env.user.show_tasks = True
        else:
            self.env.user.show_tasks = False

    @api.constrains('is_missing_info')
    def _check_missing_info(self):
        for order in self:
            if order.is_missing_info:
                order.is_missing_info_clicked = True
            else:
                invoices_condition = order.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice'
                                                                and (inv.payment_state in ('paid', 'partial') or inv.is_guarantee_invoice)
                                                                and not inv.tasks_generated)
                if not invoices_condition:
                    order.is_missing_info_clicked = False
                else:
                    if not order.project_id:
                        raise UserError(_("Cannot unset 'Missing Info' while there are qualifying invoices without a project. Please create the project first."))
                    else:
                        order.is_missing_info_clicked = False

    def action_create_project_tasks_when_missing_info(self):
        self.ensure_one()
        if self.project_id:
            raise UserError(_("Project already exists for this sale order."))

        invoices_condition = self.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice' 
                                                      and (inv.payment_state in ('paid', 'partial') or inv.is_guarantee_invoice) 
                                                      and not inv.tasks_generated)
        if not invoices_condition:
            raise UserError(_("No qualifying invoices found to generate tasks."))
        
        for invoice in invoices_condition:
            invoice._generate_tasks_from_order_button()
        
        project = self.project_id
        if not project:
            raise UserError(_("Project was not created after task generation. Please contact support."))
        
        return {
            'name': _('Project'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'view_mode': 'form',
            'res_id': project.id,
            'target': 'current',
        }

    @api.constrains('commitment_date')
    def _check_commitment_date(self):
        for order in self:
            now_plus_1h = fields.Datetime.now() + timedelta(hours=1)
            if order.commitment_date and order.commitment_date < now_plus_1h:
                raise UserError(_("The delivery date cannot be set in the past."))
            if order.project_id and order.commitment_date:
                # Convert project_id.date (date) to datetime for comparison
                project_date = order.project_id.date
                if project_date:
                    project_date_dt = fields.Datetime.to_datetime(project_date)
                else:
                    project_date_dt = None
                # Convert commitment_date to date for assignment
                commitment_date_date = order.commitment_date.date() if order.commitment_date else None
                if project_date_dt and order.commitment_date > project_date_dt:
                    order.project_id.date = commitment_date_date
                elif not order.project_id.date:
                    if not order.project_id.date_start:
                        order.project_id.date_start = fields.Datetime.now().date()
                    order.project_id.date = commitment_date_date

    def request_export_vat(self):
        self.ensure_one()
        return {
            'name': _('Export VAT Information'),
            'type': 'ir.actions.act_window',
            'res_model': 'export.vat.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_customer_id': self.partner_id.id,
                'default_type': 'invoice',
            }
        }

    @api.depends('project_id', 'show_tasks')
    def _compute_task_ids(self):
        for order in self:
            if order.project_id:
                all_tasks = self.env['project.task'].search([('project_id', '=', order.project_id.id)])
                if order.show_tasks:
                    order.task_ids = all_tasks
                else:
                    order.task_ids = all_tasks.filtered(lambda t: self.env.user in t.user_ids)
                order.task_count = len(all_tasks)
            else:
                order.task_ids = self.env['project.task']
                order.task_count = 0
    
    def action_create_project_tasks(self):
        self.ensure_one()
        if self.project_id:
            return self.project_id
        project_vals = {
            'name': self.name,
            'sale_order_id': self.id,
            'partner_id': self.partner_id.id,
            'user_id': self.user_id.id,
            'company_id': self.company_id.id,
            'allow_billable': True,
            'date_start': fields.Datetime.now(),
            'date': self.commitment_date,
            'privacy_visibility': 'followers',
            'order_id': self.id,
        }
        project = self.env['project.project'].create(project_vals)
        self.project_id = project.id

        created_tasks = self._generate_tasks_from_product_templates(project)
        if created_tasks:
            self.product_template_tasks_generated = True

        return project

    def _collect_order_products_for_task_templates(self):
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: not l.display_type and l.product_id)
        return lines.mapped('product_id')

    def _generate_tasks_from_product_templates(self, project):
        """Create project tasks from tour.task.template linked to products on sale order."""
        self.ensure_one()
        if not project:
            return self.env['project.task']

        TaskTemplate = self.env['tour.task.template']
        ProjectTask = self.env['project.task']

        products = self._collect_order_products_for_task_templates()
        if not products:
            return ProjectTask

        product_groups = {}
        for product in products:
            has_variant_template = bool(TaskTemplate.search([
                ('product_ids', 'in', [product.id]),
                ('is_active', '=', True),
            ], limit=1))

            group_key = ('variant', product.id) if has_variant_template else ('template', product.product_tmpl_id.id)
            if group_key not in product_groups:
                product_groups[group_key] = {
                    'products': self.env['product.product'],
                    'product_template': product.product_tmpl_id,
                }
            product_groups[group_key]['products'] |= product

        all_created_tasks = ProjectTask
        for _, group_data in product_groups.items():
            representative_product = group_data['products'][0]
            product_template = group_data['product_template']

            templates = TaskTemplate.get_task_from_product_id(representative_product.id)
            if not templates:
                continue

            try:
                sorted_templates = templates.get_sorted_by_dependencies()
            except Exception as exc:
                _logger.warning("Failed sorting task templates by dependencies: %s", exc)
                sorted_templates = templates

            task_map = {}
            base_datetime = self._get_product_template_task_base_datetime()

            for template in sorted_templates:
                if template.is_no_duplicate_task:
                    existing = ProjectTask.search([
                        ('project_id', '=', project.id),
                        ('name', '=', f"[{self.name}] {template.name}"),
                    ], limit=1)
                    if existing:
                        task_map[template.id] = existing
                        continue

                start_datetime = base_datetime
                if template.depends_on_ids:
                    dependent_tasks = [task_map.get(dep.id) for dep in template.depends_on_ids if dep.id in task_map]
                    deadlines = [t.date_deadline for t in dependent_tasks if t and t.date_deadline]
                    if deadlines:
                        start_datetime = max(deadlines)

                if template.start_offset_in_minutes:
                    start_datetime += timedelta(minutes=template.start_offset_in_minutes)

                duration_minutes = template.duration_in_minutes or 60
                if duration_minutes <= 0:
                    duration_minutes = 60
                deadline_datetime = start_datetime + timedelta(minutes=duration_minutes)

                user_ids = []
                if template.user_id:
                    user_ids.append(template.user_id.id)
                elif template.is_assign_salesperson and self.user_id:
                    user_ids.append(self.user_id.id)

                task_name = f"[{self.name}] {template.name}" if template.is_no_duplicate_task else f"[{product_template.name}] {template.name}"

                vals = {
                    'name': task_name,
                    'description': template.description,
                    'project_id': project.id,
                    'user_ids': [(6, 0, user_ids)] if user_ids else False,
                    'date_start': start_datetime,
                    'date_deadline': deadline_datetime,
                    'priority': template.priority or '1',
                    'tag_ids': [(6, 0, template.tags.ids)] if template.tags else False,
                    'partner_id': self.partner_id.id,
                    'mentor_id': template.mentor.id if template.mentor else False,
                    'manager_id': template.manager_id.id if template.manager_id else False,
                }

                task = ProjectTask.create(vals)
                all_created_tasks |= task
                task_map[template.id] = task

            for template in sorted_templates:
                if template.depends_on_ids and template.id in task_map:
                    task = task_map[template.id]
                    dependent_task_ids = [
                        task_map[dep.id].id
                        for dep in template.depends_on_ids
                        if dep.id in task_map and task_map[dep.id]
                    ]
                    if dependent_task_ids:
                        task.write({'depend_on_ids': [(6, 0, dependent_task_ids)]})

        if all_created_tasks:
            _logger.info(
                "Generated %s tasks from product templates for SO %s and project %s",
                len(all_created_tasks),
                self.name,
                project.name,
            )
        return all_created_tasks

    def _get_product_template_task_base_datetime(self):
        """Use the delivery date as the scheduling base for product template tasks."""
        self.ensure_one()
        return self.commitment_date or fields.Datetime.now()
    
    def action_generate_tasks_manually(self):
        """Manual action button to generate tasks"""
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund'):
                move._generate_tasks_from_invoice()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tasks Generated'),
                'message': _('Tasks have been successfully generated.'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def tour_action_view_project(self):
        self.ensure_one()
        if not self.project_id:
            return {}
        return {
            'name': _('Project'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'view_mode': 'form',
            'res_id': self.project_id.id,
            'target': 'current',
        }
    
    def action_manual_create_task(self):
        self.ensure_one()
        return {
            'name': _('Create Task Manually'),
            'type': 'ir.actions.act_window',
            'res_model': 'create.task.manual.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_order_id': self.id,
            }
        }

