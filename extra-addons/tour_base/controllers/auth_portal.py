# -*- coding: utf-8 -*-
"""Auth Portal Controller - Ket noi React Frontend voi Odoo Portal User."""

import logging
import re
import secrets

from odoo import http
from odoo.http import request

from .auth_helper import _make_response, _parse_json

_logger = logging.getLogger(__name__)


def _is_valid_email(email):
    return bool(re.match(r'^[\w.\+\-]+@[\w.\-]+\.\w{2,}$', email))


class AuthPortalController(http.Controller):

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

        expanded_items = []
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
                expanded_items.append({
                    'combo_id': combo.id,
                    'combo_name': combo.name,
                    'combo_item_id': item.id,
                    'product_id': item.product_id.id,
                    'product_name': item.product_id.display_name,
                    'selected_quantity': combo_qty,
                    'combo_item_quantity': item.quantity or 1.0,
                    'line_quantity': combo_qty * (item.quantity or 1.0),
                    # Keep same payload shape as Odoo sale combo widget.
                    'no_variant_attribute_value_ids': [],
                    'product_custom_attribute_values': [],
                })

        return _make_response({
            'code': 200,
            'message': 'OK',
            'response': {
                'product_id': product.id,
                'expanded_items': expanded_items,
                'warnings': warnings,
            }
        })

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
