import logging

from odoo import _, api, models
from odoo.exceptions import ValidationError

from odoo.addons.payment_custom.controllers.main import CustomController

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _process_notification_data(self, notification_data):
        """ Override to prevent auto-pending for custom provider """
        # Call parent for non-custom providers
        if self.provider_code != 'custom':
            return super()._process_notification_data(notification_data)
        return
    
    def confirm_custom_payment(self):
        """ Manual method to confirm custom payment with security checks """
        self.ensure_one()
        
        # Security validations
        if self.provider_code != 'custom':
            _logger.warning("Attempt to confirm non-custom payment: %s", self.reference)
            return False
            
        if self.state != 'draft':
            _logger.warning("Attempt to confirm payment in wrong state %s: %s", self.state, self.reference)
            return False
        
        # Additional security: check if transaction is recent (within 24 hours)
        from datetime import datetime, timedelta
        if self.create_date < datetime.now() - timedelta(hours=24):
            _logger.warning("Attempt to confirm old transaction: %s", self.reference)
            return False
        
        try:
            _logger.info(
                "Manually confirming custom payment for transaction with reference %s (ID: %s)",
                self.reference, self.id
            )
            self._set_pending()
            return True
        except Exception as e:
            _logger.error("Error setting transaction to pending: %s", str(e))
            return False
        
    def get_vnd_amount_format(self, amount):
        """ Format amount with currency symbol """
        self.ensure_one()
        return f"{amount:,.0f} VNĐ"