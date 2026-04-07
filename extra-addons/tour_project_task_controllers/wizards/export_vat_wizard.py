from odoo import models, fields, api, _

class ExportVATWizard(models.TransientModel):
    _name = 'export.vat.wizard'
    _description = 'Export VAT Wizard'

    customer_id = fields.Many2one('res.partner', string='Customer', required=True, domain=[('customer_rank', '>', 0)])
    vat_number = fields.Char(string='VAT Number', required=True)
    company_name = fields.Char(string='Company Name', required=True)
    address = fields.Char(string='Address')
    type = fields.Selection([
        ('invoice', 'Invoice'),
        ('bill', 'Bill')
    ])

    @api.model
    def default_get(self, fields_list):
        res = super(ExportVATWizard, self).default_get(fields_list)
        # Get customer from context if provided
        customer_id = self._context.get('default_customer_id') or res.get('customer_id')
        if customer_id:
            partner = self.env['res.partner'].browse(customer_id)
            res['customer_id'] = partner.id
            
            # Check if individual or company
            if partner.is_company or partner.company_type == 'company':
                # Direct company contact
                res['vat_number'] = partner.vat or ''
                res['company_name'] = partner.name or ''
                res['address'] = getattr(partner, 'contact_address', partner.street or '')
            else:
                # Individual contact - check if linked to a company
                if partner.parent_id and partner.parent_id.is_company:
                    # Individual linked to a company - use company's VAT
                    res['vat_number'] = partner.parent_id.vat or ''
                    res['company_name'] = partner.parent_id.name or ''
                    res['address'] = getattr(partner.parent_id, 'contact_address', partner.parent_id.street or '')
                else:
                    # Individual without company - use individual's info
                    res['vat_number'] = partner.vat or ''
                    res['company_name'] = partner.name or ''
                    res['address'] = getattr(partner, 'contact_address', partner.street or '')
        return res

    def action_export(self):
        self.ensure_one()
        
        # Get active sale order from context
        active_model = self._context.get('active_model')
        active_id = self._context.get('active_id')
        
        if active_model != 'sale.order' or not active_id:
            raise ValueError(_("This wizard must be called from a Sale Order"))
        
        sale_order = self.env['sale.order'].browse(active_id)
        
        # Get task template
        TaskTemplate = self.env['tour.task.template']
        if self.type == 'invoice':
            template = TaskTemplate.search([
                ('is_export_invoice_vat_template', '=', True), 
                ('is_active', '=', True)
            ], limit=1)
        else:
            raise NotImplementedError(_("Bill type not implemented yet"))
        
        if not template:
            raise ValueError(_("No task template found for export VAT tasks"))
        
        # Update customer VAT information if changed
        partner = self.customer_id
        values_to_update = {}
        
        # Determine target partner to update (company or individual)
        # If individual is linked to a company, update the company's VAT
        target_partner = partner
        if not partner.is_company and partner.company_type != 'company':
            # This is an individual
            if partner.parent_id and partner.parent_id.is_company:
                # Individual linked to company - update company
                target_partner = partner.parent_id
        
        # Update VAT if changed
        if target_partner.vat != self.vat_number:
            values_to_update['vat'] = self.vat_number
        
        # Update company name if changed (for company only)
        if target_partner.is_company and target_partner.name != self.company_name:
            values_to_update['name'] = self.company_name
        
        # Determine and update company_type based on VAT format
        if self.vat_number and len(self.vat_number) >= 10:
            # Company VAT typically has 10+ digits
            if target_partner.company_type != 'company':
                values_to_update['company_type'] = 'company'
                values_to_update['is_company'] = True
        else:
            # Individual/personal VAT (shorter)
            if target_partner.company_type != 'person':
                values_to_update['company_type'] = 'person'
                values_to_update['is_company'] = False
        
        # Update address if changed
        current_address = getattr(target_partner, 'contact_address', target_partner.street or '')
        if current_address != self.address:
            values_to_update['street'] = self.address
        
        # Apply updates if any
        if values_to_update:
            target_partner.write(values_to_update)
        
        # Create or get project for sale order
        if not sale_order.project_id:
            project_vals = {
                'name': sale_order.name,
                'partner_id': sale_order.partner_id.id,
                'user_id': sale_order.user_id.id,
                'company_id': sale_order.company_id.id,
            }
            project = self.env['project.project'].create(project_vals)
            sale_order.project_id = project.id
        else:
            project = sale_order.project_id
        
        # Create task from template
        task_vals = {
            'name': f"[{sale_order.name}] {template.name}",
            'description': template.description,
            'project_id': project.id,
            'user_ids': [(6, 0, [template.user_id.id] if template.user_id else [])],
            'date_start': fields.Datetime.now(),
            'priority': template.priority,
            'stage_id': self.env['project.task.type'].search([('name', '=', 'New')], limit=1).id,
        }
        
        # Add mentor and manager if available
        if hasattr(template, 'mentor') and template.mentor:
            task_vals['mentor_id'] = template.mentor.id
        if template.manager_id:
            task_vals['manager_id'] = template.manager_id.id
        
        # Calculate deadline based on duration
        if template.duration and template.duration_unit:
            from datetime import timedelta
            start_date = fields.Datetime.now()
            
            if template.duration_unit == 'hours':
                deadline = start_date + timedelta(hours=template.duration)
            elif template.duration_unit == 'days':
                deadline = start_date + timedelta(days=template.duration)
            elif template.duration_unit == 'weeks':
                deadline = start_date + timedelta(weeks=template.duration)
            else:  # minutes
                deadline = start_date + timedelta(minutes=template.duration)
            
            task_vals['date_deadline'] = deadline
        
        # Create the task
        task = self.env['project.task'].create(task_vals)
        
        # Mark sale order as export VAT processed
        sale_order.write({'is_export_vat': True})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Export VAT Task Created'),
                'message': _('Task "%s" has been created successfully. Customer information updated.') % task.name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                }
            }
        }
        

