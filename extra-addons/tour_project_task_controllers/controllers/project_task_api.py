from odoo import http
from odoo.http import request
from odoo import _
import json

class ProjectTaskAPI(http.Controller):

    def _authenticate(self):
        token = request.httprequest.headers.get('Authorization')
        if not token or not token.startswith('Bearer '):
            return False

        token = token.replace('Bearer ', '').strip()

        user_id = request.env['res.users.apikeys']._check_credentials(scope='rpc', key=token)
        if user_id:
            user = request.env['res.users'].sudo().browse(user_id)
            if not user.exists():
                return False
            request.env.user = user
            return user

        return False

    #Code 2000
    @http.route('/api/v1/project/create', type='json', auth='public', methods=['POST'], csrf=False)
    def create_project(self, **kwargs):
        """Create a new project"""
        try:
            bot = self._authenticate()
            if not bot:
                return {
                    'code': 1001,
                    'status': 'error',
                    'message': 'Authentication failed'
                }
            post = request.get_json_data()
            order_id = post.get('order_id')
            if not order_id:
                return {
                    'code': 20001,
                    'status': 'error',
                    'message': 'order_id is required'
                }
            SaleOrder = request.env['sale.order'].sudo()
            order = SaleOrder.browse(order_id)
            if not order.exists():
                return {
                    'code': 20002,
                    'status': 'error',
                    'message': 'Sale order not found'
                }
            project = order.with_user(bot).action_create_project_tasks()
            if not project:
                return {
                    'code': 20003,
                    'status': 'error',
                    'message': 'Project creation failed'
                }
            return {
                'code': 0,
                'status': 'success',
                'project_id': project.id,
                'name': project.name,
            }
        except Exception as e:
            return {
                'code': 200099,
                'status': 'error',
                'message': str(e)
            }

    #Code 2001
    @http.route('/api/v1/task/create', type='json', auth='public', methods=['POST'], csrf=False)
    def create_task(self, **kwargs):
        """Create a new task"""
        try:
            bot = self._authenticate()
            if not bot:
                return {
                    'code': 1001,
                    'status': 'error',
                    'message': 'Authentication failed'
                }
            post = request.get_json_data()
            
            invoice_id = post.get('invoice_id')
            AccountMove = request.env['account.move'].sudo()
            invoice = AccountMove.browse(invoice_id)
            if not invoice.exists():
                return {
                    'code': 20011,
                    'status': 'error',
                    'message': 'Invoice not found'
                }
            if invoice.move_type != 'out_invoice':
                return {
                    'code': 20015,
                    'status': 'error',
                    'message': 'Only customer invoices are supported'
                }
            if invoice.tasks_generated:
                return {
                    'code': 20016,
                    'status': 'error',
                    'message': 'Tasks have already been generated for this invoice'
                }
            order = invoice.order_id
            if not order.exists():
                return {
                    'code': 20012,
                    'status': 'error',
                    'message': 'Related sale order not found'
                }
            project = order.project_id
            if not project.exists():
                return {
                    'code': 20013,
                    'status': 'error',
                    'message': 'Related project not found'
                }
            
            product_ids = post.get('product_ids', [])
            ProductProduct = request.env['product.product'].sudo()
            products = ProductProduct.browse(product_ids)
            
            created_tasks = invoice.with_user(bot)._create_tasks_from_templates(products, project, order)
            if not created_tasks:
                return {
                    'code': 20014,
                    'status': 'error',
                    'message': 'No tasks were created'
                }
            invoice.with_user(bot).tasks_generated = True
            invoice.with_user(bot).message_post(
                body=_("Generated %s tasks for project %s") % (len(created_tasks), project.name),
                message_type='notification'
            )
            
            return {
                'code': 0,
                'status': 'success'
            }
        except Exception as e:
            return {
                'code': 200199,
                'status': 'error',
                'message': str(e)
            }