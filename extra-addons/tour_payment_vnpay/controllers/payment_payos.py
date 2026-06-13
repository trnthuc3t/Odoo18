# -*- coding: utf-8 -*-

import hmac
import logging
import uuid
from datetime import datetime, timedelta
from urllib import parse as urllib_parse

import requests

from odoo import http
from odoo.http import request

from odoo.addons.tour_base.controllers.auth_helper import _make_response, _parse_json


_logger = logging.getLogger(__name__)


class TourPayosPaymentController(http.Controller):

    def _collect_callback_params(self, kwargs):
        params = dict(request.httprequest.args or {})
        if kwargs:
            params.update(kwargs)
        if not params and request.httprequest.data:
            data = _parse_json(request.httprequest.data)
            if isinstance(data, dict):
                params = data
        return params

    def _is_local_url(self, url):
        try:
            host = (urllib_parse.urlparse(url).hostname or '').lower()
        except Exception:
            return False
        return host in ('localhost', '127.0.0.1', '::1')

    def _preview_amount(self, booking_payload):
        service = request.env['tour.booking.order.service'].sudo()
        savepoint = f"payos_preview_{uuid.uuid4().hex[:8]}"
        request.env.cr.execute(f"SAVEPOINT {savepoint}")
        try:
            preview = service.create_sale_order_from_payload(booking_payload)
            if preview.get('error'):
                request.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                return preview

            amount_total = float((preview.get('order') or {}).get('amount_total') or 0)
            warnings = preview.get('warnings') or []
            request.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            return {
                'status': 200,
                'amount_total': amount_total,
                'warnings': warnings,
            }
        finally:
            request.env.cr.execute(f"RELEASE SAVEPOINT {savepoint}")

    def _now_vn(self):
        return datetime.utcnow() + timedelta(hours=7)

    def _build_sign_data(self, payload):
        parts = []
        for key in sorted(payload.keys()):
            value = payload.get(key)
            if value in (None, ''):
                continue
            parts.append(f"{key}={value}")
        return '&'.join(parts)

    def _sign_payload(self, payload, checksum_key):
        sign_data = self._build_sign_data(payload)
        signature = hmac.new(checksum_key.encode('utf-8'), sign_data.encode('utf-8'), 'sha256').hexdigest()
        return sign_data, signature

    def _payos_api_request(self, url, method='POST', payload=None, headers=None):
        req_headers = {'Content-Type': 'application/json'}
        if headers:
            req_headers.update(headers)
        
        try:
            if method == 'POST':
                resp = requests.post(url, json=payload, headers=req_headers, timeout=20)
            else:  # GET
                resp = requests.get(url, headers=req_headers, timeout=20)
            return resp.status_code, _parse_json(resp.text) or {}
        except requests.exceptions.RequestException as exc:
            _logger.exception('PayOS API request error: %s', exc)
            return 500, {'message': str(exc)}

    def _payos_get_config(self):
        params = request.env['ir.config_parameter'].sudo()
        client_id = (params.get_param('tour_base.payos_client_id') or '').strip()
        api_key = (params.get_param('tour_base.payos_api_key') or '').strip()
        checksum_key = (params.get_param('tour_base.payos_checksum_key') or '').strip()
        create_url = (params.get_param('tour_base.payos_create_url') or 'https://api-merchant.payos.vn/v2/payment-requests').strip()
        payment_info_url = (params.get_param('tour_base.payos_payment_info_url') or create_url).strip()
        return_url = (params.get_param('tour_base.payos_return_url') or '').strip()
        expire_minutes = int(params.get_param('tour_base.payos_expire_minutes') or 15)

        return {
            'client_id': client_id,
            'api_key': api_key,
            'checksum_key': checksum_key,
            'create_url': create_url,
            'payment_info_url': payment_info_url,
            'return_url': return_url,
            'expire_minutes': max(expire_minutes, 1),
        }

    def _build_order_code(self):
        now = self._now_vn()
        return int(now.strftime('%y%m%d%H%M%S') + uuid.uuid4().hex[:4], 16) % 9007199254740991

    def _build_create_payload(self, booking_payload, amount, order_code, return_url, cancel_url, expired_at):
        return {
            'orderCode': int(order_code),
            'amount': int(amount),
            'description': f"Tour {booking_payload.get('product_id') or ''}"[:25],
            'returnUrl': return_url,
            'cancelUrl': cancel_url,
            'buyerName': (booking_payload.get('full_name') or '')[:255],
            'buyerEmail': (booking_payload.get('email') or '')[:255],
            'buyerPhone': (booking_payload.get('phone') or '')[:20],
            'expiredAt': int(expired_at.timestamp()),
        }

    def _payos_create_payment_link(self, payload, config):
        _, signature = self._sign_payload(
            {
                'amount': payload.get('amount'),
                'cancelUrl': payload.get('cancelUrl'),
                'description': payload.get('description'),
                'orderCode': payload.get('orderCode'),
                'returnUrl': payload.get('returnUrl'),
            },
            config['checksum_key'],
        )
        body = dict(payload)
        body['signature'] = signature
        status_code, response_payload = self._payos_api_request(
            config['create_url'],
            method='POST',
            payload=body,
            headers={
                'x-client-id': config['client_id'],
                'x-api-key': config['api_key'],
            },
        )
        return status_code, response_payload

    def _payos_get_payment_info(self, order_code, config):
        lookup_url = config['payment_info_url'].rstrip('/')
        if not lookup_url.endswith(str(order_code)):
            lookup_url = f"{lookup_url}/{order_code}"
        status_code, response_payload = self._payos_api_request(
            lookup_url,
            method='GET',
            payload=None,
            headers={
                'x-client-id': config['client_id'],
                'x-api-key': config['api_key'],
            },
        )
        return status_code, response_payload

    def _is_success_status(self, status, code, canceled):
        normalized_status = str(status or '').strip().upper()
        normalized_code = str(code or '').strip().upper()
        canceled_flag = str(canceled or '').strip().lower() in ('1', 'true', 'yes')
        if canceled_flag:
            return False
        return normalized_status in ('PAID', 'SUCCESS') or normalized_code in ('00', 'PAID', 'SUCCESS')

    @http.route('/api/payments/payos/create', type='http', auth='public', methods=['POST'], csrf=False)
    def payos_create_payment(self, **kwargs):
        data = _parse_json(request.httprequest.data)
        if data is None:
            return _make_response({'code': 400, 'message': 'JSON khong hop le', 'response': None}, 400)

        booking_payload = data.get('booking_payload') or {}
        if not isinstance(booking_payload, dict):
            return _make_response({'code': 400, 'message': 'booking_payload phai la object', 'response': None}, 400)

        config = self._payos_get_config()
        if not config['client_id'] or not config['api_key'] or not config['checksum_key']:
            return _make_response({'code': 503, 'message': 'PayOS config chua day du', 'response': None}, 503)

        create_preview = self._preview_amount(booking_payload)
        if create_preview.get('error'):
            return _make_response({'code': create_preview['status'], 'message': create_preview['error'], 'response': None}, create_preview['status'])

        amount = int(round(float(create_preview.get('amount_total') or 0)))
        if amount <= 0:
            return _make_response({'code': 400, 'message': 'So tien thanh toan khong hop le', 'response': None}, 400)

        order_code = self._build_order_code()
        request_return_url = (data.get('return_url') or '').strip()
        config_return_url = (config.get('return_url') or '').strip()
        redirect_url = request_return_url or config_return_url
        if self._is_local_url(redirect_url) and config_return_url:
            redirect_url = config_return_url
        if not redirect_url:
            return _make_response({'code': 400, 'message': 'Thieu return_url cho PayOS', 'response': None}, 400)

        request_cancel_url = (data.get('cancel_url') or '').strip()
        cancel_url = request_cancel_url or redirect_url
        if self._is_local_url(cancel_url) and config_return_url:
            cancel_url = config_return_url

        create_date = self._now_vn()
        expire_date = create_date + timedelta(minutes=config['expire_minutes'])

        create_payload = self._build_create_payload(
            booking_payload=booking_payload,
            amount=amount,
            order_code=order_code,
            return_url=redirect_url,
            cancel_url=cancel_url,
            expired_at=expire_date,
        )
        status_code, response_payload = self._payos_create_payment_link(create_payload, config)
        response_data = response_payload.get('data') or {}
        pay_url = (response_data.get('checkoutUrl') or response_data.get('checkout_url') or '').strip()
        if status_code >= 400 or not pay_url:
            message = response_payload.get('desc') or response_payload.get('message') or 'Khong the tao link thanh toan PayOS'
            return _make_response({'code': 502, 'message': message, 'response': response_payload}, 502)

        _logger.info(
            'PayOS create request: order_code=%s amount=%s return_url=%s cancel_url=%s',
            order_code,
            amount,
            redirect_url,
            cancel_url,
        )

        booking_result = request.env['tour.booking.order.service'].sudo().create_sale_order_from_payload(booking_payload)
        if booking_result.get('error'):
            message = booking_result.get('error')
            return _make_response({'code': 400, 'message': message, 'response': None}, 400)

        created_order = booking_result.get('order') or {}
        so_id = created_order.get('id')
        if so_id:
            request.env['sale.order'].sudo().browse(so_id).write({
                'client_order_ref': str(order_code),
            })

        return _make_response({
            'code': 200,
            'message': 'OK',
            'response': {
                'pay_url': pay_url,
                'order_code': order_code,
                'amount': amount,
                'result_code': 0,
                'payos_raw': response_payload,
                'so_id': so_id,
            }
        })

    @http.route('/api/payments/payos/status', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def payos_payment_status(self, **kwargs):
        params = self._collect_callback_params(kwargs)

        order_code = str(params.get('orderCode') or params.get('order_code') or '').strip()
        if not order_code:
            return _make_response({'code': 400, 'message': 'Thieu orderCode', 'response': None}, 400)

        config = self._payos_get_config()
        if not config['client_id'] or not config['api_key']:
            return _make_response({'code': 503, 'message': 'PayOS config chua day du', 'response': None}, 503)

        status_code, info_payload = self._payos_get_payment_info(order_code, config)
        info_data = info_payload.get('data') or {}

        if status_code >= 400:
            _logger.warning('PayOS get status failed order_code=%s payload=%s', order_code, info_payload)

        response_code = (params.get('code') or info_payload.get('code') or '').strip()
        status = (params.get('status') or info_data.get('status') or '').strip()
        canceled = params.get('cancel')
        amount = int(info_data.get('amount') or params.get('amount') or 0)
        is_success = self._is_success_status(status=status, code=response_code, canceled=canceled)

        so = request.env['sale.order'].sudo().search([
            ('client_order_ref', '=', str(order_code))
        ], limit=1)

        created_order = None
        if is_success and so:
            try:
                if so.state == 'draft':
                    so.action_confirm()
                created_order = {
                    'id': so.id,
                    'name': so.name,
                    'amount_total': so.amount_total,
                    'state': so.state,
                }
            except Exception as e:
                _logger.error('Failed to confirm order %s: %s', so.name, str(e))

        return _make_response({
            'code': 200,
            'message': 'OK',
            'response': {
                'order_code': order_code,
                'response_code': response_code,
                'payment_status': status,
                'result_code': 0 if is_success else 1,
                'message': info_payload.get('desc') or params.get('desc') or '',
                'amount': amount,
                'is_success': is_success,
                'payos_raw': {
                    'params': params,
                    'info': info_payload,
                },
                'order': created_order,
            }
        })

    @http.route(['/api/payments/payos/webhook', '/api/payments/payos/ipn'], type='json', auth='public', methods=['POST'], csrf=False)
    def payos_payment_webhook(self, **kwargs):
        payload = _parse_json(request.httprequest.data)
        if not isinstance(payload, dict):
            _logger.error('PayOS webhook invalid JSON')
            return {'code': -1, 'message': 'Invalid payload'}

        data = payload.get('data') or {}
        signature = (payload.get('signature') or '').strip()
        order_code = str(data.get('orderCode') or '').strip()
        if not order_code:
            _logger.error('PayOS webhook missing orderCode')
            return {'code': -1, 'message': 'Missing orderCode'}

        config = self._payos_get_config()
        if config['checksum_key'] and signature:
            _, expected_signature = self._sign_payload(data, config['checksum_key'])
            if expected_signature.lower() != signature.lower():
                _logger.error('PayOS webhook invalid signature for order_code=%s', order_code)
                return {'code': -1, 'message': 'Invalid signature'}

        so = request.env['sale.order'].sudo().search([
            ('client_order_ref', '=', str(order_code))
        ], limit=1)
        
        if not so:
            _logger.warning('PayOS webhook order not found for order_code=%s', order_code)
            return {'code': 0, 'message': 'Order not found in system'}

        expected_amount = int(round(float(so.amount_total)))
        received_amount = int(data.get('amount') or 0)
        if expected_amount and received_amount and abs(expected_amount - received_amount) > 100:
            _logger.error('PayOS webhook amount mismatch for order_code=%s expected=%s received=%s', order_code, expected_amount, received_amount)

        is_success = self._is_success_status(
            status=data.get('status') or payload.get('desc') or '',
            code=payload.get('code') or data.get('code') or '',
            canceled=data.get('cancel') or '',
        )

        if is_success and so.state == 'draft':
            try:
                so.action_confirm()
                _logger.info('PayOS webhook confirmed order %s', so.name)
            except Exception as e:
                _logger.error('PayOS webhook failed to confirm order %s: %s', so.name, str(e))

        return {'code': 0, 'message': 'OK'}
