from odoo import models, fields
import requests
import json
import hashlib
import base64
import hmac
import time

HEADERS = {
    'Content-Type': 'application/json; charset=utf-8'
}

class N8NWebhook(models.Model):
    _name = "n8n.webhook"
    _description = "N8N Webhook"

    name = fields.Char(string="Hook Name", required=True)
    short_name = fields.Char(string="Short Name", required=True)
    hook_url = fields.Char(string="Hook URL", required=True)
    hook_url_secret_key = fields.Char(string="Hook URL Secret Key", required=False, password=True)
    hook_header_key = fields.Char(string="Hook Header Key", required=False)
    is_active = fields.Boolean(string="Is Active", default=True)

    def send_hook_request(self, payload):
        if not self.is_active:
            return False
        return self.call_request(payload)

    def call_request(self, payload):
        headers = HEADERS
        if self.hook_url_secret_key and self.hook_header_key:
            headers[self.hook_header_key] = self.hook_url_secret_key

        response = requests.post(self.hook_url, data=json.dumps(payload), headers=headers)
        if response.status_code == 200:
            return True
        return False
    
    def get_n8n_job_from_short_name(self, short_name):
        return self.search([('short_name', '=', short_name), ('is_active', '=', True)], limit=1)