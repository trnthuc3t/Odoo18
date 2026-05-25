# -*- coding: utf-8 -*-

import json
import re
from datetime import datetime, time

from odoo import fields, models
from odoo.http import request


class TourBookingOrderService(models.AbstractModel):
    _name = 'tour.booking.order.service'
    _description = 'Tour Booking Order Service'

    def _is_valid_email(self, email):
        return bool(re.match(r'^[\w.\+\-]+@[\w.\-]+\.\w{2,}$', email or ''))

    def _get_user_from_react_token(self):
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return self.env['res.users']

        token = auth_header.replace('Bearer ', '').strip()
        match = re.match(r'^token_(\d+)_[A-Za-z0-9]+$', token)
        if not match:
            return self.env['res.users']

        user = self.env['res.users'].sudo().browse(int(match.group(1)))
        if user.exists() and not user._is_public():
            return user
        return self.env['res.users']

    def _get_current_website_user(self):
        token_user = self._get_user_from_react_token()
        if token_user and token_user.exists():
            return token_user

        session_uid = request.session.uid
        if session_uid:
            user = self.env['res.users'].sudo().browse(session_uid)
            if user.exists():
                return user

        user = self.env.user
        if user and user.exists() and not user._is_public():
            return user.sudo()

        return self.env['res.users']

    def _get_immediate_payment_term(self):
        payment_term_model = self.env['account.payment.term'].sudo()
        ir_model_data = self.env['ir.model.data'].sudo()

        for xmlid in (
            'account.account_payment_term_immediate',
            'account.account_payment_term_immediate_payment',
        ):
            res_id = ir_model_data._xmlid_to_res_id(xmlid, raise_if_not_found=False)
            if res_id:
                payment_term = payment_term_model.browse(res_id)
                if payment_term.exists():
                    return payment_term

        payment_term = payment_term_model.search([('name', '=', 'Immediate Payment')], limit=1)
        if payment_term:
            return payment_term

        return payment_term_model.search([('name', 'ilike', 'Immediate')], limit=1)

    def _get_or_create_guest_partner(self, full_name, email, phone):
        """Resolve a dedicated guest partner for unauthenticated checkout."""
        Partner = self.env['res.partner'].sudo()
        normalized_email = (email or '').strip().lower()
        normalized_phone = (phone or '').strip()
        fallback_name = (full_name or '').strip() or (normalized_email.split('@')[0] if normalized_email else '') or normalized_phone or 'Khach le'

        partner = self.env['res.partner']
        if normalized_email and self._is_valid_email(normalized_email):
            partner = Partner.search([('email', '=', normalized_email)], limit=1)

        if partner and partner.exists():
            updates = {}
            if fallback_name and (not partner.name or partner.name == 'Khach le'):
                updates['name'] = fallback_name
            if normalized_phone and not partner.phone:
                updates['phone'] = normalized_phone
            if updates:
                partner.write(updates)
            return partner

        return Partner.create({
            'name': fallback_name,
            'email': normalized_email or False,
            'phone': normalized_phone or False,
            'type': 'contact',
            'customer_rank': 1,
        })

    def _parse_commitment_date(self, commitment_date_value):
        if not commitment_date_value:
            return False

        if isinstance(commitment_date_value, datetime):
            return fields.Datetime.to_string(commitment_date_value)

        if isinstance(commitment_date_value, str):
            raw_value = commitment_date_value.strip()
            if not raw_value:
                return False

            try:
                selected_date = datetime.strptime(raw_value[:10], '%Y-%m-%d').date()
            except Exception:
                return False

            commitment_datetime = datetime.combine(selected_date, time(hour=12, minute=0, second=0))
            return fields.Datetime.to_string(commitment_datetime)

        return False

    def _build_selected_combo_items(self, product, combo_quantities, combo_selections=None):
        selected_combo_items = []
        warnings = []
        combo_selections = combo_selections or {}

        total_combo_quantity = 0
        for raw_qty in combo_quantities.values():
            try:
                total_combo_quantity += max(int(raw_qty), 0)
            except Exception:
                continue

        for combo in product.combo_ids:
            if getattr(combo, 'is_car_service', False):
                raw_selection = combo_selections.get(str(combo.id), combo_selections.get(combo.id))
                selected_item_ids = []
                if isinstance(raw_selection, list):
                    for raw_id in raw_selection:
                        try:
                            selected_item_ids.append(int(raw_id))
                        except Exception:
                            continue
                elif raw_selection not in (None, '', False):
                    try:
                        selected_item_ids = [int(raw_selection)]
                    except Exception:
                        selected_item_ids = []

                if not selected_item_ids:
                    continue

                selected_items = combo.combo_item_ids.filtered(lambda i: i.id in selected_item_ids)
                if not selected_items:
                    warnings.append(f'Lua chon car service cho combo {combo.name} khong hop le')
                    continue

                for item in selected_items:
                    min_qty = item.min_quantity or 0
                    max_qty = item.max_quantity or 0
                    if max_qty > 0:
                        is_valid_qty_range = min_qty <= total_combo_quantity <= max_qty
                    else:
                        is_valid_qty_range = total_combo_quantity >= min_qty

                    if not is_valid_qty_range:
                        warnings.append(
                            f'Car service {item.product_id.display_name} khong hop le voi tong so luong combo {total_combo_quantity} '
                            f'(yeu cau min={min_qty}, max={max_qty})'
                        )
                        continue

                    selected_combo_items.append({
                        'combo_id': combo.id,
                        'combo_name': combo.name,
                        'combo_item_id': item.id,
                        'product_id': item.product_id.id,
                        'product_name': item.product_id.display_name,
                        'selected_quantity': 1,
                        'combo_item_quantity': item.quantity or 1.0,
                        'line_quantity': item.quantity or 1.0,
                        'no_variant_attribute_value_ids': [],
                        'product_custom_attribute_values': [],
                    })
                continue

            raw_qty = combo_quantities.get(str(combo.id), combo_quantities.get(combo.id, 0))
            try:
                combo_qty = int(raw_qty)
            except Exception:
                combo_qty = 0

            if combo_qty <= 0:
                continue

            if not combo.combo_item_ids:
                warnings.append(f'Combo {combo.name} khong co combo item')
                continue

            for item in combo.combo_item_ids:
                selected_combo_items.append({
                    'combo_id': combo.id,
                    'combo_name': combo.name,
                    'combo_item_id': item.id,
                    'product_id': item.product_id.id,
                    'product_name': item.product_id.display_name,
                    'selected_quantity': combo_qty,
                    'combo_item_quantity': item.quantity or 1.0,
                    'line_quantity': combo_qty * (item.quantity or 1.0),
                    'no_variant_attribute_value_ids': [],
                    'product_custom_attribute_values': [],
                })

        return selected_combo_items, warnings

    def _create_combo_child_lines(self, order, parent_line, product, selected_combo_items):
        SaleOrderLine = self.env['sale.order.line'].sudo()

        if not selected_combo_items:
            return

        section_offset = 0
        if getattr(product, 'is_combo_multiple_choice', False) or getattr(product, 'is_day_tour', False):
            combo_item_ids = [item['combo_item_id'] for item in selected_combo_items]
            combo_items = self.env['product.combo.item'].sudo().browse(combo_item_ids)
            combo_names = combo_items.mapped('combo_id.name')
            unique_combo_names = list(dict.fromkeys(combo_names))
            section_name = ' + '.join(unique_combo_names)

            SaleOrderLine.create({
                'order_id': order.id,
                'display_type': 'line_note',
                'name': section_name,
                'sequence': parent_line.sequence + 1,
                'linked_line_id': parent_line.id,
            })
            section_offset = 1

        for item_index, combo_item in enumerate(selected_combo_items, start=1):
            combo_item_record = self.env['product.combo.item'].sudo().browse(combo_item['combo_item_id'])
            selected_qty = combo_item.get('selected_quantity') or 1
            try:
                selected_qty = max(int(selected_qty), 1)
            except Exception:
                selected_qty = 1

            if getattr(product, 'is_day_tour', False):
                item_qty = parent_line.product_uom_qty
            elif getattr(product, 'is_combo_multiple_choice', False) and combo_item_record.quantity:
                item_qty = parent_line.product_uom_qty * combo_item_record.quantity * selected_qty
            else:
                item_qty = parent_line.product_uom_qty * selected_qty

            child_vals = {
                'order_id': order.id,
                'product_id': combo_item['product_id'],
                'product_uom_qty': item_qty,
                'combo_item_id': combo_item['combo_item_id'],
                'sequence': parent_line.sequence + section_offset + item_index,
                'linked_line_id': parent_line.id,
            }

            no_variant_ids = combo_item.get('no_variant_attribute_value_ids') or []
            if no_variant_ids:
                child_vals['product_no_variant_attribute_value_ids'] = [(6, 0, no_variant_ids)]

            custom_values = combo_item.get('product_custom_attribute_values') or []
            if custom_values:
                child_vals['product_custom_attribute_value_ids'] = [(0, 0, value) for value in custom_values]

            SaleOrderLine.create(child_vals)

    def create_sale_order_from_payload(self, data):
        product_id = data.get('product_id')
        if not product_id:
            return {'error': 'Thieu product_id', 'status': 400}

        try:
            product_id = int(product_id)
        except Exception:
            return {'error': 'product_id khong hop le', 'status': 400}

        try:
            product_qty = int(data.get('product_qty', 1))
        except Exception:
            product_qty = 1
        product_qty = max(product_qty, 1)

        combo_quantities = data.get('combo_quantities') or {}
        if not isinstance(combo_quantities, dict):
            return {'error': 'combo_quantities phai la object', 'status': 400}

        combo_selections = data.get('combo_selections') or {}
        if not isinstance(combo_selections, dict):
            return {'error': 'combo_selections phai la object', 'status': 400}

        product = self.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok:
            return {'error': 'San pham khong ton tai', 'status': 404}

        variant_id = data.get('variant_id')
        variant = self.env['product.product']
        if variant_id:
            try:
                variant_id = int(variant_id)
                variant = self.env['product.product'].sudo().browse(variant_id)
                if not variant.exists() or variant.product_tmpl_id.id != product.id:
                    return {'error': 'Bien the san pham khong hop le', 'status': 400}
            except Exception:
                return {'error': 'variant_id khong hop le', 'status': 400}

        if not variant:
            variant = product.product_variant_id or self.env['product.product'].sudo().search([
                ('product_tmpl_id', '=', product.id)
            ], limit=1)
        if not variant:
            return {'error': 'Khong tim thay bien the san pham', 'status': 400}

        full_name = (data.get('full_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip().lower()

        current_user = self._get_current_website_user()
        is_authenticated_user = bool(current_user and current_user.exists() and not current_user._is_public())
        if is_authenticated_user:
            partner = current_user.partner_id.sudo()
        else:
            partner = self._get_or_create_guest_partner(full_name=full_name, email=email, phone=phone)

        partner_updates = {}
        if full_name and is_authenticated_user:
            partner_updates['name'] = full_name
        if phone:
            partner_updates['phone'] = phone
        if email and self._is_valid_email(email):
            partner_updates['email'] = email
        if partner_updates:
            partner.write(partner_updates)

        payment_method = (data.get('payment_method') or '').strip()
        special_requests = (data.get('special_requests') or '').strip()
        commitment_date = self._parse_commitment_date(data.get('commitment_date'))
        payment_term = self._get_immediate_payment_term()
        note_parts = []
        if payment_method:
            note_parts.append(f'Payment method: {payment_method}')
        if special_requests:
            note_parts.append(f'Yeu cau dac biet: {special_requests}')

        order_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
            'note': '\n'.join(note_parts) if note_parts else False,
        }

        if product.type != 'combo':
            web_pricelist = self.env['product.pricelist'].sudo().browse(2)
            if web_pricelist.exists():
                order_vals['pricelist_id'] = web_pricelist.id

        if payment_term:
            order_vals['payment_term_id'] = payment_term.id

        if commitment_date:
            order_vals['commitment_date'] = commitment_date

        order = self.env['sale.order'].sudo().create(order_vals)

        line_vals = {
            'order_id': order.id,
            'product_id': variant.id,
            'product_uom_qty': product_qty,
        }

        selected_combo_items = []
        warnings = []
        if product.type == 'combo' and (combo_quantities or combo_selections):
            selected_combo_items, warnings = self._build_selected_combo_items(product, combo_quantities, combo_selections)
            if selected_combo_items:
                line_vals['selected_combo_items'] = json.dumps(selected_combo_items)

        parent_line = self.env['sale.order.line'].sudo().create(line_vals)

        if selected_combo_items:
            self._create_combo_child_lines(order, parent_line, product, selected_combo_items)
            parent_line.sudo().write({'selected_combo_items': False})

        order.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])

        return {
            'order': {
                'id': order.id,
                'name': order.name,
                'state': order.state,
                'amount_total': order.amount_total,
                'amount_untaxed': order.amount_untaxed,
                'amount_tax': order.amount_tax,
                'currency': order.currency_id.name if order.currency_id else 'VND',
            },
            'warnings': warnings,
            'status': 201,
        }
