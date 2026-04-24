# -*- coding: utf-8 -*-
"""Auth Portal Controller - Ket noi React Frontend voi Odoo Portal User."""

import logging
import json
import re
import secrets

from odoo import http
from odoo.http import request

from .auth_helper import _make_response, _parse_json

_logger = logging.getLogger(__name__)


def _is_valid_email(email):
    return bool(re.match(r'^[\w.\+\-]+@[\w.\-]+\.\w{2,}$', email))


class AuthPortalController(http.Controller):

    def _build_selected_combo_items(self, product, combo_quantities):
        selected_combo_items = []
        warnings = []

        for combo in product.combo_ids:
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
        SaleOrderLine = request.env['sale.order.line'].sudo()

        if not selected_combo_items:
            return

        section_offset = 0
        if getattr(product, 'is_combo_multiple_choice', False) or getattr(product, 'is_day_tour', False):
            combo_item_ids = [item['combo_item_id'] for item in selected_combo_items]
            combo_items = request.env['product.combo.item'].sudo().browse(combo_item_ids)
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
            combo_item_record = request.env['product.combo.item'].sudo().browse(combo_item['combo_item_id'])
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

    @http.route('/api/auth/register', type='http', auth='public', methods=['POST'], csrf=False)
    def register(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        phone = (data.get('phone') or '').strip()
        password = data.get('password') or ''

        # Validation
        errors = {}
        if not name or len(name) < 2:
            errors['name'] = 'Ho va ten phai it nhat 2 ky tu'
        if not email:
            errors['email'] = 'Email khong duoc de trong'
        elif not _is_valid_email(email):
            errors['email'] = 'Dinh dang email khong hop le'
        if not password or len(password) < 8:
            errors['password'] = 'Mat khau phai it nhat 8 ky tu'

        if errors:
            return _make_response({'code': 400, 'message': 'Validation failed', 'response': errors}, 400)

        # Check email exists
        existing = request.env['res.users'].sudo().search([('login', '=', email)], limit=1)
        if existing:
            return _make_response({'code': 409, 'message': 'Email da duoc su dung', 'response': {'error_code': 'EMAIL_EXISTS'}}, 409)

        try:
            portal_group = request.env.ref('base.group_portal')
            company = request.env['res.company'].sudo().search([], limit=1, order='id')

            user = request.env['res.users'].sudo().with_context(
                no_reset_password=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                tracking_disable=True,
            ).create({
                'name': name,
                'login': email,
                'email': email,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'groups_id': [(6, 0, [portal_group.id])],
            })

            crypt_value = request.env['res.users'].sudo()._crypt_context().hash(password)
            request.cr.execute(
                "UPDATE res_users SET password = %s WHERE id = %s",
                [crypt_value, user.id]
            )
            request.cr.commit()

            if phone:
                user.partner_id.sudo().write({'phone': phone})

        except Exception as e:
            _logger.warning("Failed to create portal user: %s", str(e))
            return _make_response({'code': 500, 'message': 'Khong the tao tai khoan', 'response': str(e)}, 500)

        _logger.info("Portal user registered: id=%s, email=%s", user.id, email)

        return _make_response({
            'code': 201,
            'message': 'Dang ky thanh cong',
            'response': {
                'user': {
                    'id': user.id,
                    'name': user.name,
                    'email': user.login,
                    'partner_id': user.partner_id.id,
                    'phone': phone,
                },
                'token': 'token_%s_%s' % (user.id, secrets.token_hex(8)),
                'expires_in': 7 * 24 * 3600,
            }
        }, 201)

    # AUTH - LOGIN

    @http.route('/api/auth/login', type='http', auth='public', methods=['POST'], csrf=False)
    def login(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not email or not password:
            return _make_response({'code': 400, 'message': 'Email va mat khau khong duoc de trong', 'response': None}, 400)

        try:
            auth_result = request.session.authenticate(request.env.cr.dbname, {
                'type': 'password',
                'login': email,
                'password': password,
            })
            if not auth_result:
                return _make_response({'code': 401, 'message': 'Email hoac mat khau khong dung', 'response': None}, 401)
            uid = auth_result.get('uid')
        except Exception as e:
            _logger.warning("Authentication failed for %s: %s", email, str(e))
            return _make_response({'code': 401, 'message': 'Email hoac mat khau khong dung', 'response': None}, 401)

        user = request.env['res.users'].sudo().browse(uid)
        if not user.exists():
            return _make_response({'code': 401, 'message': 'Tai khoan khong ton tai', 'response': None}, 401)

        csrf_token = request.csrf_token()
        _logger.info("User logged in: id=%s, email=%s", uid, email)

        return _make_response({
            'code': 200,
            'message': 'Dang nhap thanh cong',
            'response': {
                'user': {
                    'id': uid,
                    'name': user.name,
                    'email': user.login,
                    'partner_id': user.partner_id.id,
                },
                'token': 'token_%s_%s' % (uid, secrets.token_hex(8)),
                'session_id': request.session.sid,
                'csrf_token': csrf_token,
                'expires_in': 7 * 24 * 3600,
            }
        })

    # AUTH - LOGOUT

    @http.route('/api/auth/logout', type='http', auth='user', methods=['POST'], csrf=False)
    def logout(self, **kwargs):
        user_id = request.env.user.id
        request.session.logout()
        _logger.info("User logged out: user=%s", user_id)
        return _make_response({
            'code': 200,
            'message': 'Dang xuat thanh cong',
            'response': {'message': 'Dang xuat thanh cong'},
        })

    # AUTH - ME

    @http.route('/api/auth/me', type='http', auth='user', methods=['POST'], csrf=False)
    def me(self, **kwargs):
        try:
            user = request.env.user
            partner = user.partner_id
            return _make_response({
                'code': 200,
                'message': 'OK',
                'response': {
                    'user': {
                        'id': user.id,
                        'name': user.name,
                        'email': user.login,
                        'phone': partner.phone or '',
                        'partner_id': partner.id,
                    }
                }
            })
        except Exception as e:
            _logger.error("Error getting current user: %s", str(e))
            return _make_response({'code': 500, 'message': 'Khong the lay thong tin user', 'response': None}, 500)

    # AUTH - FORGOT PASSWORD

    @http.route('/api/auth/forgot-password', type='http', auth='public', methods=['POST'], csrf=False)
    def forgot_password(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        email = (data.get('email') or '').strip().lower()
        if not email or not _is_valid_email(email):
            return _make_response({'code': 400, 'message': 'Email khong hop le', 'response': None}, 400)

        try:
            user = request.env['res.users'].sudo().search([('login', '=', email)], limit=1)
            if user.exists():
                user.with_context(create_user=False).action_reset_password()
                _logger.info("Password reset requested for: %s", email)
        except Exception as e:
            _logger.warning("Forgot password error for %s: %s", email, str(e))

        # Luon tra ve success de khong tiet lo thong tin email co ton tai
        return _make_response({
            'code': 200,
            'message': 'Da gui lien ket dat lai mat khau',
            'response': {'message': 'Da gui lien ket dat lai mat khau'},
        })

    # AUTH - REFRESH TOKEN

    @http.route('/api/auth/refresh', type='http', auth='user', methods=['POST'], csrf=False)
    def refresh_token(self, **kwargs):
        user = request.env.user
        return _make_response({
            'code': 200,
            'message': 'Refresh thanh cong',
            'response': {
                'token': 'token_%s_%s' % (user.id, secrets.token_hex(8)),
                'expires_in': 7 * 24 * 3600,
            }
        })

    # PRODUCTS - LIST

    @http.route('/api/products', type='http', auth='public', methods=['GET'], csrf=False)
    def get_products(self, **kwargs):
        try:
            limit = int(kwargs.get('limit', 20))
            offset = int(kwargs.get('offset', 0))
            search = (kwargs.get('search') or '').strip()

            limit = min(max(limit, 1), 100)

            domain = [('sale_ok', '=', True)]
            if search:
                domain.append(('name', 'ilike', f'%{search}%'))

            Product = request.env['product.template'].sudo()
            total = Product.search_count(domain)
            products = Product.search(domain, limit=limit, offset=offset)

            items = []
            for p in products:
                is_combo = (p.type == 'combo')
                items.append({
                    'id': p.id,
                    'name': p.name,
                    'default_code': p.default_code or '',
                    'list_price': p.list_price,
                    'currency': p.currency_id.name if p.currency_id else 'VND',
                    'description': p.description_sale or '',
                    'detail_information': getattr(p, 'detail_information', '') or '',
                    'image_url': f'/web/image/product.template/{p.id}/image_1920/300x300' if p.image_1920 else '',
                    'type': p.type or 'consu',
                    'is_combo': is_combo,
                    'is_combo_multiple_choice': bool(getattr(p, 'is_combo_multiple_choice', False)) if is_combo else False,
                    'is_day_tour': bool(getattr(p, 'is_day_tour', False)) if is_combo else False,
                    'has_combos': bool(p.combo_ids) if is_combo else False,
                })

            return _make_response({
                'code': 200,
                'message': 'Lay danh sach san pham thanh cong',
                'response': {
                    'products': items,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                }
            })
        except Exception as e:
            _logger.error("Error getting products: %s", str(e))
            return _make_response({'code': 500, 'message': 'Khong the lay danh sach san pham', 'response': None}, 500)

    # PRODUCTS - DETAIL

    @http.route('/api/products/<int:product_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_product_detail(self, product_id):
        """Lay chi tiet 1 san pham."""
        try:
            product = request.env['product.template'].sudo().browse(product_id)
            if not product.exists() or not product.sale_ok:
                return _make_response({'code': 404, 'message': 'San pham khong ton tai', 'response': None}, 404)

            combos = []
            for combo in product.combo_ids:
                combo_items = []
                for item in combo.combo_item_ids:
                    combo_items.append({
                        'id': item.id,
                        'combo_item_id': item.id,
                        'product_id': item.product_id.id,
                        'product_name': item.product_id.display_name,
                        'extra_price': item.extra_price,
                        'fixed_price': item.fixed_price,
                        'quantity': item.quantity or 1.0,
                        'min_quantity': item.min_quantity,
                        'max_quantity': item.max_quantity,
                        'shared_cost_enabled': item.shared_cost_enabled,
                    })
                combos.append({
                    'id': combo.id,
                    'name': combo.name,
                    'items': combo_items,
                })

            return _make_response({
                'code': 200,
                'message': 'OK',
                'response': {
                    'product': {
                        'id': product.id,
                        'name': product.name,
                        'default_code': product.default_code or '',
                        'list_price': product.list_price,
                        'currency': product.currency_id.name if product.currency_id else 'VND',
                        'description': product.description_sale or '',
                        'detail_information': getattr(product, 'detail_information', '') or '',
                        'image_url': f'/web/image/product.template/{product.id}/image_1920/600x600' if product.image_1920 else '',
                        'type': product.type or 'consu',
                        'is_combo': product.type == 'combo',
                        'is_combo_multiple_choice': bool(getattr(product, 'is_combo_multiple_choice', False)),
                        'is_day_tour': bool(getattr(product, 'is_day_tour', False)),
                    },
                    'combos': combos,
                }
            })
        except Exception as e:
            _logger.error("Error getting product detail: %s", str(e))
            return _make_response({'code': 500, 'message': 'Khong the lay chi tiet san pham', 'response': None}, 500)

    @http.route('/api/products/<int:product_id>/combo-items', type='http', auth='user', methods=['POST'], csrf=False)
    def prepare_combo_items(self, product_id, **kwargs):
        """Expand selected combo quantities into all combo items automatically.        """
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        combo_quantities = data.get('combo_quantities') or {}
        if not isinstance(combo_quantities, dict):
            return _make_response({'code': 400, 'message': 'combo_quantities phai la object', 'response': None}, 400)

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok:
            return _make_response({'code': 404, 'message': 'San pham khong ton tai', 'response': None}, 404)

        if product.type != 'combo':
            return _make_response({'code': 400, 'message': 'San pham nay khong phai combo', 'response': None}, 400)

        expanded_items, warnings = self._build_selected_combo_items(product, combo_quantities)

        return _make_response({
            'code': 200,
            'message': 'OK',
            'response': {
                'product_id': product.id,
                'expanded_items': expanded_items,
                'warnings': warnings,
            }
        })

    @http.route('/api/orders', type='http', auth='user', methods=['POST'], csrf=False)
    def create_order(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        product_id = data.get('product_id')
        if not product_id:
            return _make_response({'code': 400, 'message': 'Thieu product_id', 'response': None}, 400)

        try:
            product_id = int(product_id)
        except Exception:
            return _make_response({'code': 400, 'message': 'product_id khong hop le', 'response': None}, 400)

        try:
            product_qty = int(data.get('product_qty', 1))
        except Exception:
            product_qty = 1
        product_qty = max(product_qty, 1)

        combo_quantities = data.get('combo_quantities') or {}
        if not isinstance(combo_quantities, dict):
            return _make_response({'code': 400, 'message': 'combo_quantities phai la object', 'response': None}, 400)

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok:
            return _make_response({'code': 404, 'message': 'San pham khong ton tai', 'response': None}, 404)

        variant = product.product_variant_id or request.env['product.product'].sudo().search([
            ('product_tmpl_id', '=', product.id)
        ], limit=1)
        if not variant:
            return _make_response({'code': 400, 'message': 'Khong tim thay bien the san pham', 'response': None}, 400)

        partner = request.env.user.partner_id.sudo()
        full_name = (data.get('full_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip().lower()

        partner_updates = {}
        if full_name:
            partner_updates['name'] = full_name
        if phone:
            partner_updates['phone'] = phone
        if email and _is_valid_email(email):
            partner_updates['email'] = email
        if partner_updates:
            partner.write(partner_updates)

        payment_method = (data.get('payment_method') or '').strip()
        special_requests = (data.get('special_requests') or '').strip()
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

        try:
            order = request.env['sale.order'].sudo().create(order_vals)

            line_vals = {
                'order_id': order.id,
                'product_id': variant.id,
                'product_uom_qty': product_qty,
            }

            selected_combo_items = []
            warnings = []
            if product.type == 'combo' and combo_quantities:
                selected_combo_items, warnings = self._build_selected_combo_items(product, combo_quantities)
                if selected_combo_items:
                    line_vals['selected_combo_items'] = json.dumps(selected_combo_items)

            parent_line = request.env['sale.order.line'].sudo().create(line_vals)

            if selected_combo_items:
                self._create_combo_child_lines(order, parent_line, product, selected_combo_items)
                parent_line.sudo().write({'selected_combo_items': False})

            order.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])

            return _make_response({
                'code': 201,
                'message': 'Tao don hang thanh cong',
                'response': {
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
                }
            }, 201)
        except Exception as e:
            _logger.error('Error creating order: %s', str(e))
            return _make_response({'code': 500, 'message': 'Khong the tao don hang', 'response': str(e)}, 500)

    # AUTH - SET API KEY (admin only)

    @http.route('/api/auth/api-key/set', type='http', auth='user', methods=['POST'], csrf=False)
    def set_api_key(self, **kwargs):
        if request.env.user.id != 2:
            return _make_response({'code': 403, 'message': 'Chi tai khoan Admin co quyen', 'response': None}, 403)

        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        new_key = (data.get('api_key') or '').strip()
        if not new_key or len(new_key) < 8:
            return _make_response({'code': 400, 'message': 'API Key phai it nhat 8 ky tu', 'response': None}, 400)

        try:
            request.env.user.write({'api_key': new_key})
        except Exception as e:
            return _make_response({'code': 500, 'message': str(e), 'response': None}, 500)

        _logger.info("API key updated for admin user (id=2)")
        return _make_response({
            'code': 200,
            'message': 'Cap nhat thanh cong',
            'response': {'api_key': new_key, 'message': 'API Key da duoc cap nhat'},
        })
