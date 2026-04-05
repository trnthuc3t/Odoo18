from odoo import http, fields as odoo_fields
from odoo.http import request
from odoo.addons.sale.controllers.combo_configurator import SaleComboConfiguratorController


class ComboMultipleChoiceController(http.Controller):

    @http.route('/api/is_combo_multiple_choice', type='json', auth='user')
    def is_combo_multiple_choice(self, product_template_id):
        ProductTemplate = request.env['product.template'].sudo()
        product = ProductTemplate.browse(product_template_id)
        result = False
        if product.exists():
            result = bool(getattr(product, 'is_combo_multiple_choice', False))
        return result

    @http.route('/api/is_day_tour', type='json', auth='user')
    def is_day_tour(self, product_template_id):
        ProductTemplate = request.env['product.template'].sudo()
        product = ProductTemplate.browse(product_template_id)
        result = False
        if product.exists():
            result = bool(getattr(product, 'is_day_tour', False))
        return result

    @http.route('/api/day_tour/get_combo_items', type='json', auth='user')
    def get_day_tour_combo_items(self, product_template_id, customer_quantity, currency_id=None):
        """Get combo items for a day tour product based on customer quantity.

        For each combo, returns ALL combo items with min_quantity <= customer_quantity and max_quantity >= customer_quantity
        If no items match, falls back to the item with the lowest min_quantity and highest max_quantity.
        """
        product_template_id = int(product_template_id)
        customer_quantity = int(customer_quantity)

        product = request.env['product.template'].sudo().browse(product_template_id)
        if not product.exists() or not product.is_day_tour:
            return {'combos': []}

        target_currency = None
        if currency_id:
            target_currency = request.env['res.currency'].browse(int(currency_id))

        conversion_date = odoo_fields.Date.today()

        result_combos = []
        for combo in product.combo_ids:
            items = combo.combo_item_ids.sorted(key=lambda x: x.min_quantity)
            matched_items = items.filtered(lambda i: i.min_quantity <= customer_quantity and i.max_quantity >= customer_quantity)

            # Fallback to the item with the lowest min_quantity and highest max_quantity if none matched
            if not matched_items and items:
                matched_items = items[0]

            for matched_item in matched_items:
                fixed_price = matched_item.fixed_price or 0
                if target_currency and matched_item.currency_id and matched_item.currency_id != target_currency:
                    fixed_price = matched_item.currency_id._convert(
                        from_amount=fixed_price,
                        to_currency=target_currency,
                        company=combo.company_id or request.env.company,
                        date=conversion_date,
                    )

                shared = bool(matched_item.shared_cost_enabled)
                price_per_person = (fixed_price / customer_quantity) if shared and customer_quantity > 0 else fixed_price

                result_combos.append({
                    'combo_id': combo.id,
                    'combo_name': combo.name,
                    'combo_item_id': matched_item.id,
                    'product_id': matched_item.product_id.id,
                    'product_name': matched_item.product_id.display_name,
                    'fixed_price': fixed_price,
                    'price_per_person': price_per_person,
                    'shared_cost_enabled': shared,
                    'min_quantity': matched_item.min_quantity,
                    'max_quantity': matched_item.max_quantity,
                })

        return {'combos': result_combos}


class ComboMultipleChoiceConfiguratorController(SaleComboConfiguratorController):
    """Override combo configurator to use lst_price instead of extra_price for multiple choice combos."""

    def _get_combo_item_data(
        self, combo, combo_item, selected_combo_item, date, currency, pricelist, **kwargs
    ):
        """Override to return lst_price for combo multiple choice products and convert extra_price currency."""
        # Get base data from parent
        data = super()._get_combo_item_data(
            combo, combo_item, selected_combo_item, date, currency, pricelist, **kwargs
        )
        
        # CRITICAL FIX: Convert extra_price from company currency to order currency
        # This fixes the bug where 200,000 VND becomes 200,000 USD
        if currency and combo_item.extra_price:
            converted_extra_price = request.env['product.combo.item'].get_extra_price_in_currency(
                combo_item_id=combo_item.id,
                target_currency_id=currency.id,
                date=date,
                company_id=combo.company_id.id if combo.company_id else None,
            )
            data['extra_price'] = converted_extra_price
        
        # Check if this combo belongs to a combo multiple choice product
        product_templates = combo.env['product.template'].search([
            ('combo_ids', 'in', combo.id)
        ])
        
        is_combo_multiple_choice = any(
            pt.is_combo_multiple_choice for pt in product_templates 
            if hasattr(pt, 'is_combo_multiple_choice')
        )
        
        if is_combo_multiple_choice:
            # For combo multiple choice, use fixed_price if set, otherwise fallback to lst_price + extra_price
            if combo_item.fixed_price:
                # Use fixed_price with currency conversion
                fixed_price = combo_item.fixed_price
                if combo_item.currency_id and currency and combo_item.currency_id != currency:
                    fixed_price = combo_item.currency_id._convert(
                        from_amount=fixed_price,
                        to_currency=currency,
                        company=combo.company_id or request.env.company,
                        date=date,
                    )
                data['fixed_price'] = fixed_price
                data['use_fixed_price'] = True
            else:
                # Fallback: use lst_price + extra_price (already converted above)
                lst_price = combo_item.product_id.lst_price
                if combo_item.currency_id and currency and combo_item.currency_id != currency:
                    lst_price = combo_item.currency_id._convert(
                        from_amount=lst_price,
                        to_currency=currency,
                        company=combo.company_id or request.env.company,
                        date=date,
                    )
                data['lst_price'] = lst_price
                data['use_lst_price'] = True
            
            # Add quantity info for multiple choice combo
            data['quantity'] = combo_item.quantity or 1.0
        
        return data