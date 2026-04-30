# -*- coding: utf-8 -*-

from odoo.http import request


SESSION_KEY = 'tour_livechat_customer_identity'


def build_livechat_identity(user):
    partner = user.partner_id
    return {
        'user_id': user.id,
        'partner_id': partner.id,
        'name': user.name or '',
        'email': user.login or user.email or '',
        'phone': partner.phone or '',
    }


def format_livechat_identity(identity):
    if not identity:
        return False

    parts = []
    if identity.get('name'):
        parts.append(identity['name'])
    if identity.get('email'):
        parts.append(identity['email'])
    if identity.get('phone'):
        parts.append(identity['phone'])

    return ' | '.join(parts) or 'Visitor'


def get_livechat_identity():
    try:
        identity = request.session.get(SESSION_KEY)
    except RuntimeError:
        return None
    return identity if isinstance(identity, dict) else None


def get_livechat_display_name():
    return format_livechat_identity(get_livechat_identity())


def set_livechat_identity(user):
    identity = build_livechat_identity(user)
    request.session[SESSION_KEY] = identity
    return identity


def clear_livechat_identity():
    request.session.pop(SESSION_KEY, None)
