from odoo import models, api


class ProductComboItem(models.Model):
    _inherit = 'product.combo.item'

    @api.model
    def get_extra_price_in_currency(self, combo_item_id, target_currency_id, date, company_id=None):
        """
        Convert extra_price from company currency to target currency.
        
        :param int combo_item_id: The combo item ID
        :param int target_currency_id: Target currency ID
        :param datetime date: Date for currency conversion
        :param int company_id: Company ID (optional)
        :return: Converted extra price
        """
        combo_item = self.browse(combo_item_id)
        if not combo_item.exists():
            return 0.0
        
        # Get company (either from combo_item or parameter or default)
        company = combo_item.company_id or (
            self.env['res.company'].browse(company_id) if company_id 
            else self.env.company
        )
        
        # Get source currency (company currency where extra_price was defined)
        source_currency = company.currency_id
        
        # Get target currency
        target_currency = self.env['res.currency'].browse(target_currency_id)
        
        # If currencies are the same, no conversion needed
        if source_currency == target_currency:
            return combo_item.extra_price
        
        # Convert extra_price from company currency to target currency
        converted_price = source_currency._convert(
            from_amount=combo_item.extra_price,
            to_currency=target_currency,
            company=company,
            date=date,
        )
        
        return converted_price
