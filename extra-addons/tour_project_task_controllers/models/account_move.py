from odoo import models, fields, api, _
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_runtime_environment(self):
        self.ensure_one()
        return self.env['ir.config_parameter'].sudo().get_param('web.base.env', default='local')

    is_guarantee_invoice = fields.Boolean(
        string='Is Guarantee Invoice', 
        default=False, 
        copy=False,
        help="Check if invoice is guaranteed to trigger task generation"
    )
    tasks_generated = fields.Boolean(
        string="Tasks Generated", 
        default=False, 
        copy=False,
        help="Prevent duplicate task generation"
    )
    
    @api.constrains('payment_state')
    def _constraints_payment_state(self):
        for record in self:
            if record.payment_state in ('paid', 'parital') and not record.tasks_generated:
                if record._get_runtime_environment() == 'local':
                    record._generate_tasks_from_invoice()
                else:
                    record._generate_tasks_from_invoice_queue()
    
    def _generate_tasks_from_order_button(self):
        self.ensure_one()
        
        # Prevent duplicate generation
        if self.tasks_generated:
            return
        
        # Only for customer invoices
        if self.move_type != "out_invoice":
            return
        
        order = self.order_id
        if not order:
            return
        
        # Get or create project for this order
        project = self._get_or_create_project(order)
        if not project:
            return
        
        products = self.invoice_line_ids.filtered(lambda l: l.product_id and l.display_type == 'product').mapped('product_id')
        
        if not products:
            return
        
        # Create tasks from templates
        created_tasks = self._create_tasks_from_templates(products, project, order)
        
        if created_tasks:
            self.tasks_generated = True
            _logger.info(f"Generated {len(created_tasks)} tasks for invoice {self.name}")
            
            # Post notification to invoice
            self.message_post(
                body=_("Generated %s tasks for project %s") % (len(created_tasks), project.name),
                message_type='notification'
            )

    def _generate_tasks_from_invoice(self):
        self.ensure_one()
        
        # Prevent duplicate generation
        if self.tasks_generated:
            return
        
        # Only for customer invoices
        if self.move_type != "out_invoice":
            return
        
        order = self.order_id
        if not order:
            return
        
        if not order.project_id and order.is_missing_info:
            return
        
        # Get or create project for this order
        project = self._get_or_create_project(order)
        if not project:
            return
        
        products = self.invoice_line_ids.filtered(lambda l: l.product_id and l.display_type == 'product').mapped('product_id')
        
        if not products:
            return
        
        # Create tasks from templates
        created_tasks = self._create_tasks_from_templates(products, project, order)
        
        if created_tasks:
            self.tasks_generated = True
            _logger.info(f"Generated {len(created_tasks)} tasks for invoice {self.name}")
            
            # Post notification to invoice
            self.message_post(
                body=_("Generated %s tasks for project %s") % (len(created_tasks), project.name),
                message_type='notification'
            )

    def _generate_tasks_from_invoice_queue(self):
        self.ensure_one()
        
        # Prevent duplicate generation
        if self.tasks_generated:
            return
        
        # Only for customer invoices
        if self.move_type != "out_invoice":
            return
        
        order = self.order_id
        if not order:
            return
        
        if not order.project_id and order.is_missing_info:
            return
        
        N8NConnector = self.env['n8n.webhook'].sudo()
        LarkMessageConnector = self.env['lark.message.hook'].sudo()
        base_url = self.get_base_url()
        lark_message_job = LarkMessageConnector.get_lark_job_from_short_name('project_task_queue_v1')
        n8n_job = N8NConnector.get_n8n_job_from_short_name('project_task_queue_v1')

        if not order.project_id:
            project_create_url = f"{base_url}/api/v1/project/create"
            payload = {
                "payload": {
                    "order_id": order.id,
                },
                "url_callback": project_create_url
            }
            if not n8n_job:
                if lark_message_job:
                    lark_message_job.send_basic_message("Error:\nN8N Job 'project_task_queue_v1' không tìm thấy hoặc bị inactive - sử dụng tạo project/task ngay.\nInvoice: %s" % self.name)
                self._generate_tasks_from_invoice()
                return
            
            if lark_message_job:
                lark_message_job.send_basic_message("STEP 1:\nGửi request đến N8N Job 'project_task_queue_v1' để tạo project/task.\nOrder: %s" % order.name)
            request = n8n_job.send_hook_request(payload)
            if not request:
                if lark_message_job:
                    lark_message_job.send_basic_message("Error:\nGửi request đến N8N Job 'project_task_queue_v1' thất bại - sử dụng tạo project/task ngay.\nInvoice: %s" % self.name)
                self._generate_tasks_from_invoice()
                return
            if lark_message_job:
                lark_message_job.send_basic_message("STEP 1 SUCCESS:\nGửi request đến N8N Job 'project_task_queue_v1' thành công.\nOrder: %s" % order.name)
        
        products = self.invoice_line_ids.filtered(lambda l: l.product_id and l.display_type == 'product').mapped('product_id')
        
        if not products:
            return
        
        if lark_message_job:
            lark_message_job.send_basic_message("STEP 2:\nBắt đầu tạo task từ template cho order %s." % order.name)
        
        task_create_url = f"{base_url}/api/v1/task/create"
        payload = {
            "payload": {
                "invoice_id": self.id,
                "product_ids": products.ids
            },
            "url_callback": task_create_url
        }
        request = n8n_job.send_hook_request(payload)
        if not request:
            if lark_message_job:
                lark_message_job.send_basic_message("Error:\nGửi request đến N8N Job 'project_task_queue_v1' thất bại - Yêu cầu tạo thủ công các tasks từ invoice.\nInvoice: %s\nOrder: %s" % (self.name, order.name))
            return
        if lark_message_job:
            lark_message_job.send_basic_message("STEP 2 SUCCESS:\nGửi request đến N8N Job 'project_task_queue_v1' thành công - Đang chờ tạo task từ invoice.\nInvoice: %s\nOrder: %s" % (self.name, order.name))
    
    def _get_or_create_project(self, order):
        # Check if project already exists using order_id
        project = self.order_id.project_id
        
        if project:
            return project
        
        project = self.order_id.action_create_project_tasks()
        return project
    
    def _create_tasks_from_templates(self, products, project, order):
        """
        Create project.task records from task templates
        Each product/product group gets its own set of tasks
        
        Args:
            products: product.product recordset
            project: project.project record
            order: sale.order record
            
        Returns:
            list of project.task records
        """
        TaskTemplate = self.env['tour.task.template']
        
        # Group products by their task generation strategy
        # Key: (product_template_id, has_variant_specific_template)
        product_groups = {}
        
        for product in products:
            # Check if this specific variant has its own template
            variant_templates = TaskTemplate.search([
                ('product_ids', 'in', [product.id]),
                ('is_active', '=', True)
            ], limit=1)
            
            has_variant_template = bool(variant_templates)
            
            # If variant has specific template, create separate group
            # Otherwise group by product_template_id
            if has_variant_template:
                group_key = ('variant', product.id)
            else:
                group_key = ('template', product.product_tmpl_id.id)
            
            if group_key not in product_groups:
                product_groups[group_key] = {
                    'products': self.env['product.product'],
                    'product_template': product.product_tmpl_id,
                }
            
            product_groups[group_key]['products'] |= product
        
        _logger.info(f"Grouped {len(products)} products into {len(product_groups)} task generation groups")
        
        # Create tasks for each product group
        all_created_tasks = []
        
        for group_key, group_data in product_groups.items():
            group_products = group_data['products']
            product_template = group_data['product_template']
            representative_product = group_products[0]
            templates = TaskTemplate.get_task_from_product_id(representative_product.id)
            if not templates:
                _logger.info(f"No task templates found for product group: {product_template.name}")
                continue
            try:
                sorted_templates = templates.get_sorted_by_dependencies()
            except Exception as e:
                _logger.error(f"Error sorting templates by dependencies: {e}")
                sorted_templates = templates
            created_tasks = []
            task_map = {}
            base_datetime = fields.Datetime.now()
            for template in sorted_templates:
                # Nếu template is_no_duplicate_task, kiểm tra project đã có task này chưa
                if template.is_no_duplicate_task:
                    existing_task = self.env['project.task'].search([
                        ('project_id', '=', project.id),
                        ('name', '=', f"[{order.name}] {template.name}")
                    ], limit=1)
                    if existing_task:
                        _logger.info(f"Task '{existing_task.name}' đã tồn tại cho project {project.name}, bỏ qua tạo thêm.")
                        task_map[template.id] = existing_task
                        continue
                # Calculate start datetime based on dependencies
                start_datetime = base_datetime
                if template.depends_on_ids:
                    dependent_tasks = [task_map.get(dep.id) for dep in template.depends_on_ids if dep.id in task_map]
                    if dependent_tasks:
                        deadlines = [t.date_deadline for t in dependent_tasks if t and t.date_deadline]
                        if deadlines:
                            start_datetime = max(deadlines)
                # Tạo task
                task = self._create_task_from_template(
                    template,
                    project,
                    order,
                    start_datetime,
                    product_template,
                    is_no_duplicate_task=template.is_no_duplicate_task
                )
                if task:
                    created_tasks.append(task)
                    task_map[template.id] = task
            # Set dependencies sau khi tạo xong
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
            all_created_tasks.extend(created_tasks)
            _logger.info(f"Created {len(created_tasks)} tasks for product group: {product_template.name}")
        return all_created_tasks
    
    def _create_task_from_template(self, template, project, order, base_datetime, product_template=None, is_no_duplicate_task=False):
        """
        Create a single project.task from template
        Copy all template data to task without linking template_id
        
        Args:
            template: tour.task.template record
            project: project.project record
            order: sale.order record
            base_datetime: datetime for scheduling
            product_template: product.template record (optional) for task name prefix
            is_no_duplicate_task: bool, nếu True thì task chỉ tạo 1 lần cho project, tên task là [Tên Sale Order] Tên task
            
        Returns:
            project.task record
        """
        # Calculate dates
        start_datetime = base_datetime
        if template.start_offset_in_minutes:
            start_datetime += timedelta(minutes=template.start_offset_in_minutes)
        
        # Calculate deadline based on duration
        # Ensure deadline is always after start_datetime
        duration_minutes = template.duration_in_minutes if template.duration_in_minutes else 0
        if duration_minutes <= 0:
            # Default to 1 hour if duration is invalid
            duration_minutes = 60
        
        deadline_datetime = start_datetime + timedelta(minutes=duration_minutes)
        
        # Determine assigned user
        user_ids = []
        if template.user_id:
            user_ids.append(template.user_id.id)
        elif template.is_assign_salesperson and order.user_id:
            user_ids.append(order.user_id.id)
        
        # Build task name
        if is_no_duplicate_task:
            task_name = f"[{order.name}] {template.name}"
        else:
            task_name = template.name
            if product_template:
                task_name = f"[{product_template.name}] {template.name}"
        
        # Build task values - copy from template
        task_vals = {
            'name': task_name,
            'description': template.description,
            'project_id': project.id,
            'user_ids': [(6, 0, user_ids)] if user_ids else False,
            'date_deadline': deadline_datetime,
            'date_start': start_datetime,
            'priority': template.priority or '1',
            'tag_ids': [(6, 0, template.tags.ids)] if template.tags else False,
            'partner_id': order.partner_id.id,
            # Copy mentor and manager
            'mentor_id': template.mentor.id if template.mentor else False,
            'manager_id': template.manager_id.id if template.manager_id else False,
        }
        
        task = self.env['project.task'].create(task_vals)
        
        _logger.info(f"Created task '{task.name}' from template '{template.name}' for project {project.name}")
        
        return task
    
    def confirm_and_guarantee_payment(self):
        """Confirm the invoice and guarantee the payment."""
        self.ensure_one()
        self.action_post()
        self.is_guarantee_invoice = True
        if self.tasks_generated:
            return
        if not self.move_type == "out_invoice":
            return
        if self._get_runtime_environment() == 'local':
            self._generate_tasks_from_invoice()
        else:
            self._generate_tasks_from_invoice_queue()
