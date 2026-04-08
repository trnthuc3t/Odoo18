from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, UserError, ValidationError
import json
import logging

_logger = logging.getLogger(__name__)


class CustomPaymentController(http.Controller):

    @http.route('/payment/custom/confirm', type='json', auth='public', methods=['POST'], csrf=True)
    def confirm_custom_payment(self, tx_id=None, **kwargs):
        response = {'success': False, 'error': None}
        if not tx_id:
            response['error'] = 'Missing required parameters'
            return response
        try:
            tx_id = int(tx_id)
        except (ValueError, TypeError):
            response['error'] = 'Invalid transaction ID'
            return response
        
        try:
            # Find transaction with security checks
            tx = request.env['payment.transaction'].sudo().search([
                ('id', '=', tx_id),
                ('provider_code', '=', 'custom')
            ], limit=1)
            
            if not tx:
                _logger.warning("Invalid payment confirmation attempt: tx_id=%s", tx_id)
                response['error'] = 'Transaction not found or invalid access'
                return response
            
            # Additional security checks
            if tx.state not in ['draft']:
                response['error'] = f'Payment cannot be confirmed in current state: {tx.state}'
                return response
            
            # Confirm payment
            success = tx.confirm_custom_payment()
            if success:
                _logger.info("Successfully confirmed custom payment for tx: %s (ID: %s)", tx.reference, tx.id)
                response['success'] = True
                
                # Additional security: log the confirmation
                tx.message_post(
                    body=f"Payment manually confirmed via web interface",
                    message_type='notification'
                )
            else:
                response['error'] = 'Failed to confirm payment - transaction may be in wrong state'
                
        except (AccessError, UserError, ValidationError) as e:
            _logger.warning("Access/Validation error in payment confirmation: %s", str(e))
            response['error'] = 'Access denied or validation failed'
            
        except Exception as e:
            _logger.error("Unexpected error confirming custom payment: %s", str(e), exc_info=True)
            response['error'] = 'Internal server error'
        
        return response