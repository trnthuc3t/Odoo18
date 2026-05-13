# -*- coding: utf-8 -*-
"""Auth Portal Controller - Ket noi React Frontend voi Odoo Portal User."""

import logging
import json
import re
import secrets
import base64
from datetime import datetime, time

from odoo import http, fields
from odoo.http import request

from .auth_helper import _make_response, _parse_json

_logger = logging.getLogger(__name__)


def _is_valid_email(email):
    return bool(re.match(r'^[\w.\+\-]+@[\w.\-]+\.\w{2,}$', email))


class AuthPortalController(http.Controller):

    def _get_realtime_channel_model_name(self):
        registry = request.env.registry
        if 'discuss.channel' in registry.models:
            return 'discuss.channel'
        if 'mail.channel' in registry.models:
            return 'mail.channel'
        return False

    def _get_realtime_member_model_name(self):
        registry = request.env.registry
        if 'discuss.channel.member' in registry.models:
            return 'discuss.channel.member'
        if 'mail.channel.member' in registry.models:
            return 'mail.channel.member'
        return False

    def _build_product_image_url(self, product, size='600x600'):
        if not product or not product.exists() or not product.image_1920:
            return ''
        version = int(product.write_date.timestamp()) if product.write_date else 0
        return f'/api/products/{product.id}/image/{size}?v={version}'

    def _get_user_from_react_token(self):
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return request.env['res.users']

        token = auth_header.replace('Bearer ', '').strip()
        match = re.match(r'^token_(\d+)_[A-Za-z0-9]+$', token)
        if not match:
            return request.env['res.users']

        user = request.env['res.users'].sudo().browse(int(match.group(1)))
        if user.exists() and not user._is_public():
            return user
        return request.env['res.users']

    def _get_chat_api_user(self):
        token_user = self._get_user_from_react_token()
        if token_user and token_user.exists():
            return token_user
        return self._get_current_website_user()

    def _get_or_create_realtime_channel(self, partner):
        channel_model = self._get_realtime_channel_model_name()
        if not channel_model:
            return request.env['res.users']

        channel_name = f'WEBCHAT:{partner.id}'
        Channel = request.env[channel_model].sudo()

        channel = Channel.search([('name', '=', channel_name)], limit=1)

        admin_group = request.env.ref('base.group_system', raise_if_not_found=False)
        admin_domain = [
            ('share', '=', False),
            ('active', '=', True),
        ]
        if admin_group:
            admin_domain.append(('groups_id', 'in', [admin_group.id]))
        admin_users = request.env['res.users'].sudo().search(admin_domain)
        if not admin_users:
            admin_users = request.env['res.users'].sudo().search([
                ('share', '=', False),
                ('active', '=', True),
            ], limit=1)

        partner_ids = list({partner.id, *admin_users.mapped('partner_id').ids})

        if channel:
            if channel_model == 'discuss.channel':
                existing_members = channel.channel_member_ids
                existing_partner_ids = set(existing_members.mapped('partner_id').ids)
                missing_partner_ids = [pid for pid in partner_ids if pid not in existing_partner_ids]
                remove_member_ids = existing_members.filtered(
                    lambda m: m.partner_id.id not in partner_ids
                ).ids

                member_commands = []
                if remove_member_ids:
                    member_commands.extend([(2, member_id, 0) for member_id in remove_member_ids])
                if missing_partner_ids:
                    member_commands.extend([
                        (0, 0, {'partner_id': partner_id}) for partner_id in missing_partner_ids
                    ])

                write_vals = {}
                if member_commands:
                    write_vals['channel_member_ids'] = member_commands
                if write_vals:
                    channel.write(write_vals)
            else:
                existing_partner_ids = set(channel.channel_partner_ids.ids)
                write_vals = {}
                if set(partner_ids) != existing_partner_ids:
                    write_vals['channel_partner_ids'] = [(6, 0, partner_ids)]
                if write_vals:
                    channel.write(write_vals)
            return channel

        create_vals = {
            'name': channel_name,
            'channel_type': 'chat',
        }
        if channel_model == 'discuss.channel':
            create_vals['channel_member_ids'] = [
                (0, 0, {'partner_id': partner_id}) for partner_id in partner_ids
            ]
        else:
            create_vals['channel_partner_ids'] = [(6, 0, partner_ids)]
        if 'public' in Channel._fields:
            create_vals['public'] = 'private'
        return Channel.create(create_vals)

    def _is_channel_member(self, channel, partner):
        if not channel or not channel.exists() or not partner or not partner.exists():
            return False
        if partner in channel.channel_partner_ids:
            return True

        member_model = self._get_realtime_member_model_name()
        if not member_model:
            return False

        member_count = request.env[member_model].sudo().search_count([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', partner.id),
        ])
        return bool(member_count)

    def _get_current_website_user(self):
        # token_user = self._get_user_from_react_token()
        # if token_user and token_user.exists():
        #     return token_user

        session_uid = request.session.uid
        if session_uid:
            user = request.env['res.users'].sudo().browse(session_uid)
            if user.exists():
                return user

        user = request.env.user
        if user and user.exists() and not user._is_public():
            return user.sudo()

        return request.env['res.users']

    def _get_immediate_payment_term(self):
        """Return the Immediate Payment term if available."""
        payment_term_model = request.env['account.payment.term'].sudo()
        ir_model_data = request.env['ir.model.data'].sudo()

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

        payment_term = payment_term_model.search([('name', 'ilike', 'Immediate')], limit=1)
        return payment_term

    def _parse_commitment_date(self, commitment_date_value):
        """Parse a date string from React into an Odoo datetime string."""
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

        try:
            auth_result = request.session.authenticate(request.env.cr.dbname, {
                'type': 'password',
                'login': email,
                'password': password,
            })
            if not auth_result:
                raise ValueError('Failed to authenticate new portal user')
        except Exception as e:
            _logger.warning("Portal user created but auto-login failed for %s: %s", email, str(e))
            return _make_response({'code': 500, 'message': 'Tai khoan da tao nhung khong the dang nhap tu dong', 'response': None}, 500)

        _logger.info("Portal user registered: id=%s, email=%s", user.id, email)
        csrf_token = request.csrf_token()

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
                'session_id': request.session.sid,
                'csrf_token': csrf_token,
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
            user = self._get_current_website_user()
            if not user or not user.exists():
                return _make_response({'code': 401, 'message': 'Not authenticated', 'response': None}, 401)
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

    @http.route('/api/rt-chat/session', type='http', auth='public', methods=['POST'], csrf=False)
    def rt_chat_session(self, **kwargs):
        user = self._get_chat_api_user()
        if not user or not user.exists() or user._is_public():
            return _make_response({'code': 401, 'message': 'Not authenticated', 'response': None}, 401)

        channel_model = self._get_realtime_channel_model_name()
        if not channel_model:
            return _make_response({'code': 503, 'message': 'Realtime channel model not available', 'response': None}, 503)

        partner = user.partner_id
        if not partner:
            return _make_response({'code': 400, 'message': 'User has no partner', 'response': None}, 400)

        channel = self._get_or_create_realtime_channel(partner)
        last_msg = request.env['mail.message'].sudo().search([
            ('model', '=', channel_model),
            ('res_id', '=', channel.id),
        ], order='id desc', limit=1)

        return _make_response({
            'code': 200,
            'message': 'Realtime chat session ready',
            'response': {
                'channel_id': channel.id,
                'channel_name': channel.name,
                'partner_id': partner.id,
                'last_message_id': last_msg.id if last_msg else 0,
            }
        })

    @http.route('/api/rt-chat/messages', type='http', auth='public', methods=['GET'], csrf=False)
    def rt_chat_messages(self, **kwargs):
        user = self._get_chat_api_user()
        if not user or not user.exists() or user._is_public():
            return _make_response({'code': 401, 'message': 'Not authenticated', 'response': None}, 401)

        channel_model = self._get_realtime_channel_model_name()
        if not channel_model:
            return _make_response({'code': 503, 'message': 'Realtime channel model not available', 'response': None}, 503)

        partner = user.partner_id
        try:
            channel_id = int(kwargs.get('channel_id', 0))
            after_id = int(kwargs.get('after_id', 0))
        except Exception:
            return _make_response({'code': 400, 'message': 'channel_id or after_id khong hop le', 'response': None}, 400)

        channel = request.env[channel_model].sudo().browse(channel_id)
        if not channel.exists():
            return _make_response({'code': 404, 'message': 'Channel not found', 'response': None}, 404)

        if not self._is_channel_member(channel, partner):
            return _make_response({'code': 403, 'message': 'Forbidden channel', 'response': None}, 403)

        messages = request.env['mail.message'].sudo().search([
            ('model', '=', channel_model),
            ('res_id', '=', channel.id),
            ('id', '>', after_id),
            ('message_type', 'in', ['comment', 'email', 'notification']),
        ], order='id asc', limit=100)

        serialized = []
        last_id = after_id
        for msg in messages:
            serialized.append({
                'id': msg.id,
                'body': msg.body or '',
                'author_name': msg.author_id.name if msg.author_id else 'System',
                'author_partner_id': msg.author_id.id if msg.author_id else False,
                'date': fields.Datetime.to_string(msg.date) if msg.date else '',
                'is_mine': bool(msg.author_id and msg.author_id.id == partner.id),
            })
            last_id = msg.id

        return _make_response({
            'code': 200,
            'message': 'OK',
            'response': {
                'messages': serialized,
                'last_message_id': last_id,
                'channel_id': channel.id,
            }
        })

    @http.route('/api/rt-chat/send', type='http', auth='public', methods=['POST'], csrf=False)
    def rt_chat_send(self, **kwargs):
        user = self._get_chat_api_user()
        if not user or not user.exists() or user._is_public():
            return _make_response({'code': 401, 'message': 'Not authenticated', 'response': None}, 401)

        channel_model = self._get_realtime_channel_model_name()
        if not channel_model:
            return _make_response({'code': 503, 'message': 'Realtime channel model not available', 'response': None}, 503)

        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        try:
            channel_id = int(data.get('channel_id', 0))
        except Exception:
            channel_id = 0
        body = (data.get('message') or '').strip()

        if not channel_id or not body:
            return _make_response({'code': 400, 'message': 'channel_id va message la bat buoc', 'response': None}, 400)

        channel = request.env[channel_model].sudo().browse(channel_id)
        if not channel.exists():
            return _make_response({'code': 404, 'message': 'Channel not found', 'response': None}, 404)

        partner = user.partner_id
        if not self._is_channel_member(channel, partner):
            return _make_response({'code': 403, 'message': 'Forbidden channel', 'response': None}, 403)

        try:
            message = channel.with_user(user).message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=partner.id,
            )
        except Exception:
            message = channel.sudo().message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=partner.id,
            )

        return _make_response({
            'code': 200,
            'message': 'Message sent',
            'response': {
                'id': message.id,
                'channel_id': channel.id,
                'body': message.body or '',
                'author_name': partner.name,
                'author_partner_id': partner.id,
                'date': fields.Datetime.to_string(message.date) if message.date else '',
            }
        })

    # PRODUCTS - LIST

    @http.route('/api/products/<int:product_id>/image/<string:size>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_product_image(self, product_id, size='600x600', **kwargs):
        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok or not product.image_1920:
            return request.not_found()

        try:
            image_binary = base64.b64decode(product.image_1920)
        except Exception:
            return request.not_found()

        content_type = 'application/octet-stream'
        if image_binary.startswith(b'\x89PNG'):
            content_type = 'image/png'
        elif image_binary.startswith(b'\xff\xd8'):
            content_type = 'image/jpeg'
        elif image_binary.startswith(b'RIFF') and image_binary[8:12] == b'WEBP':
            content_type = 'image/webp'

        return request.make_response(
            image_binary,
            headers=[
                ('Content-Type', content_type),
                ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
            ],
        )

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
                    'tour_duration': getattr(p, 'tour_duration', '') or '',
                    'tour_location_address': getattr(p, 'tour_location_address', '') or '',
                    'tour_location_map_url': getattr(p, 'tour_location_map_url', '') or '',
                    'image_url': self._build_product_image_url(p, '600x600'),
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
                    'is_car_service': bool(getattr(combo, 'is_car_service', False)),
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
                        'tour_duration': getattr(product, 'tour_duration', '') or '',
                        'tour_location_address': getattr(product, 'tour_location_address', '') or '',
                        'tour_location_map_url': getattr(product, 'tour_location_map_url', '') or '',
                        'image_url': self._build_product_image_url(product, '1200x600'),
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

        combo_selections = data.get('combo_selections') or {}
        if not isinstance(combo_selections, dict):
            return _make_response({'code': 400, 'message': 'combo_selections phai la object', 'response': None}, 400)

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok:
            return _make_response({'code': 404, 'message': 'San pham khong ton tai', 'response': None}, 404)

        if product.type != 'combo':
            return _make_response({'code': 400, 'message': 'San pham nay khong phai combo', 'response': None}, 400)

        expanded_items, warnings = self._build_selected_combo_items(product, combo_quantities, combo_selections)

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

        combo_selections = data.get('combo_selections') or {}
        if not isinstance(combo_selections, dict):
            return _make_response({'code': 400, 'message': 'combo_selections phai la object', 'response': None}, 400)

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.sale_ok:
            return _make_response({'code': 404, 'message': 'San pham khong ton tai', 'response': None}, 404)

        variant = product.product_variant_id or request.env['product.product'].sudo().search([
            ('product_tmpl_id', '=', product.id)
        ], limit=1)
        if not variant:
            return _make_response({'code': 400, 'message': 'Khong tim thay bien the san pham', 'response': None}, 400)

        current_user = self._get_current_website_user()
        if not current_user or not current_user.exists():
            return _make_response({'code': 401, 'message': 'Not authenticated', 'response': None}, 401)

        partner = current_user.partner_id.sudo()
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

        if payment_term:
            order_vals['payment_term_id'] = payment_term.id

        if commitment_date:
            order_vals['commitment_date'] = commitment_date

        try:
            order = request.env['sale.order'].sudo().create(order_vals)

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

    @http.route('/api/orders/history', type='http', auth='user', methods=['GET'], csrf=False)
    def get_order_history(self, **kwargs):
        """Lay lich su don du lich cua user dang dang nhap."""
        current_user = self._get_current_website_user()
        if not current_user or not current_user.exists() or current_user._is_public():
            return _make_response({'code': 401, 'message': 'Not authenticated', 'response': None}, 401)

        partner = current_user.partner_id.sudo()

        params = request.httprequest.args
        try:
            limit = int(params.get('limit', 20))
        except Exception:
            limit = 20
        try:
            offset = int(params.get('offset', 0))
        except Exception:
            offset = 0

        limit = max(1, min(limit, 100))
        offset = max(offset, 0)

        include_all_states = str(params.get('include_all', '')).lower() in ('1', 'true', 'yes')

        domain = [('partner_id', '=', partner.id)]
        if not include_all_states:
            domain.append(('state', 'in', ['sale', 'done']))

        Order = request.env['sale.order'].sudo()

        try:
            total = Order.search_count(domain)
            orders = Order.search(domain, order='date_order desc, id desc', limit=limit, offset=offset)

            state_labels = dict(Order._fields['state'].selection)

            data_orders = []
            for order in orders:
                lines = []
                for line in order.order_line.filtered(lambda l: not l.display_type):
                    lines.append({
                        'id': line.id,
                        'product_id': line.product_id.id,
                        'product_name': line.product_id.display_name,
                        'quantity': line.product_uom_qty,
                        'price_unit': line.price_unit,
                        'price_subtotal': line.price_subtotal,
                        'price_total': line.price_total,
                        'image_url': f'/web/image/product.product/{line.product_id.id}/image_128/128x128' if line.product_id.image_128 else '',
                    })

                data_orders.append({
                    'id': order.id,
                    'name': order.name,
                    'state': order.state,
                    'state_label': state_labels.get(order.state, order.state),
                    'date_order': order.date_order.isoformat() if order.date_order else '',
                    'amount_untaxed': order.amount_untaxed,
                    'amount_tax': order.amount_tax,
                    'amount_total': order.amount_total,
                    'currency': order.currency_id.name if order.currency_id else 'VND',
                    'line_count': len(lines),
                    'lines': lines,
                })

            return _make_response({
                'code': 200,
                'message': 'OK',
                'response': {
                    'orders': data_orders,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                }
            })
        except Exception as e:
            _logger.error('Error fetching order history: %s', str(e))
            return _make_response({'code': 500, 'message': 'Khong the lay lich su don hang', 'response': str(e)}, 500)


    @http.route('/api/tours-for-chunking', type='http', auth='public', methods=['GET'], csrf=False)
    def get_tours_for_chunking(self, **kwargs):
        # Lấy danh sách tour không chứa ảnh cho việc chunking dữ liệu vào vector database, chỉ lấy các trường cần thiết và giới hạn độ dài text để tránh lỗi khi lưu trữ
        try:
            try:
                limit = int(request.httprequest.args.get('limit', '50'))
                offset = int(request.httprequest.args.get('offset', '0'))
            except (ValueError, TypeError):
                limit = 50
                offset = 0
            
            if limit < 1 or limit > 500:
                limit = 50
            if offset < 0:
                offset = 0
            
            _logger.info(f"Fetching tours for chunking: limit={limit}, offset={offset}")
            
            Tour = request.env['product.template'].sudo()
            
            total_tours = Tour.search_count([
                ('type', '=', 'combo'),
                ('sale_ok', '=', True)
            ])
            
            tours = Tour.search([
                ('type', '=', 'combo'),
                ('sale_ok', '=', True)
            ], order='id asc', offset=offset, limit=limit)

            tours_data = []
            for tour in tours:
                try:
                    description = tour.description_sale or ''
                    detail_info = getattr(tour, 'detail_information', '') or ''
                    
                    if description and len(description) > 500:
                        description = description[:500]
                    
                    if detail_info and len(detail_info) > 500:
                        detail_info = detail_info[:500]
                    
                    category_name = tour.categ_id.name if tour.categ_id else 'General'
                    
                    created_at = tour.create_date.isoformat() if tour.create_date else ''
                    updated_at = tour.write_date.isoformat() if tour.write_date else ''
                    
                    tours_data.append({
                        'id': tour.id,
                        'name': tour.name,
                        'category': category_name,
                        'price': tour.list_price,
                        'currency': tour.currency_id.name if tour.currency_id else 'VND',
                        'description': description,
                        'detail_information': detail_info,
                        'created_at': created_at,
                        'updated_at': updated_at,
                    })
                except Exception as e:
                    _logger.warning(f"Error processing tour {tour.id}: {e}")
                    continue

            current_page = (offset // limit) + 1 if limit > 0 else 1
            has_more = (offset + limit) < total_tours if total_tours > 0 else False
            
            return _make_response({
                'code': 200,
                'message': f'Lay {len(tours_data)} tour thanh cong (trang {current_page})',
                'response': {
                    'tours': tours_data,
                    'total': total_tours,
                    'limit': limit,
                    'offset': offset,
                    'has_more': has_more
                }
            })
        except Exception as e:
            _logger.error(f'Error in get_tours_for_chunking: {str(e)}', exc_info=True)
            return _make_response({
                'code': 500,
                'message': 'Khong the lay tour',
                'response': str(e)
            }, 500)


    @http.route('/api/tours', type='http', auth='public', methods=['GET'], csrf=False)
    def get_tours_for_rag(self, **kwargs):
        try:
            # Parse pagination parameters with safe defaults
            try:
                limit = int(request.httprequest.args.get('limit', '100'))
                offset = int(request.httprequest.args.get('offset', '0'))
            except (ValueError, TypeError) as e:
                _logger.warning(f"Invalid pagination params: {e}")
                limit = 100
                offset = 0
            
            # Validate and sanitize parameters
            if limit < 1:
                limit = 100
            elif limit > 1000:
                limit = 1000
                
            if offset < 0:
                offset = 0
            
            _logger.info(f"Fetching tours with limit={limit}, offset={offset}")
            
            Tour = request.env['product.template'].sudo()
            
            # Build search domain
            domain = [
                ('type', '=', 'combo'),
                ('sale_ok', '=', True)
            ]
            
            try:
                total_tours = Tour.search_count(domain)
            except Exception as e:
                _logger.warning(f"search_count failed, trying fallback: {e}")
                total_tours = 0
            
            try:
                tours = Tour.search(domain, order='id asc', offset=offset, limit=limit)
            except Exception as e:
                _logger.warning(f"search with offset/limit failed, trying without: {e}")
                tours = Tour.search(domain, order='id asc')
                tours = tours[offset:offset + limit]

            tours_data = []
            for tour in tours:
                try:
                    description = tour.description_sale or ''
                    detail_info = getattr(tour, 'detail_information', '') or ''
                    
                    if description and len(description) > 1500:
                        description = description[:1500]
                    
                    if detail_info and len(detail_info) > 1500:
                        detail_info = detail_info[:1500]
                    
                    full_description = f"{tour.name}\n\n{description}\n\n{detail_info}".strip()
                    
                    category_name = tour.categ_id.name if tour.categ_id else 'General'
                    
                    image_url = f'/web/image/product.template/{tour.id}/image_1920'
                    
                    created_at = tour.create_date.isoformat() if tour.create_date else ''
                    updated_at = tour.write_date.isoformat() if tour.write_date else ''
                    
                    tours_data.append({
                        'id': tour.id,
                        'name': tour.name,
                        'category': category_name,
                        'price': tour.list_price,
                        'currency': tour.currency_id.name if tour.currency_id else 'VND',
                        'description': description,
                        'detail_information': detail_info,
                        'full_text': full_description,
                        'image_url': image_url,
                        'created_at': created_at,
                        'updated_at': updated_at,
                    })
                except Exception as e:
                    _logger.warning(f"Error processing tour {tour.id}: {e}")
                    continue

            current_page = (offset // limit) + 1 if limit > 0 else 1
            has_more = (offset + limit) < total_tours if total_tours > 0 else False
            
            return _make_response({
                'code': 200,
                'message': f'Lay {len(tours_data)} tour thanh cong (trang {current_page})',
                'response': {
                    'tours': tours_data,
                    'total': total_tours,
                    'limit': limit,
                    'offset': offset,
                    'has_more': has_more
                }
            })
        except Exception as e:
            _logger.error(f'Error in get_tours_for_rag: {str(e)}', exc_info=True)
            return _make_response({
                'code': 500,
                'message': 'Khong the lay tour',
                'response': str(e)
            }, 500)

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
