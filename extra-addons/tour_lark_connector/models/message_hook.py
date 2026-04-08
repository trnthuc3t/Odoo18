from odoo import models, fields, api
import requests
import json
import hashlib
import base64
import hmac
import time

HEADERS = {
    'Content-Type': 'application/json; charset=utf-8'
}

class LarkMessageHook(models.Model):
    _name = "lark.message.hook"
    _description = "Lark Message Hook"

    name = fields.Char(string="Hook Name", required=True)
    short_name = fields.Char(string="Short Name", required=True)
    hook_url = fields.Char(string="Hook URL", required=True)
    hook_url_signature = fields.Char(string="Hook URL with Signature", required=False, password=True)
    is_active = fields.Boolean(string="Is Active", default=True)

    def send_basic_message(self, message):
        if not self.is_active:
            return False
        payload = {
            "msg_type": "text",
            "content": {
                "text": message
            }
        }
        return self.call_request(payload)

    def call_request(self, payload):
        headers = HEADERS
        if self.hook_url_signature:
            timestamp = str(int(time.time()))
            secret = self.gen_sign(timestamp, self.hook_url_signature)
            payload['timestamp'] = timestamp
            payload['sign'] = secret
        response = requests.post(self.hook_url, data=json.dumps(payload), headers=headers)
        if response.status_code == 200:
            return True
        return False
    
    def get_lark_job_from_short_name(self, short_name):
        return self.search([('short_name', '=', short_name), ('is_active', '=', True)], limit=1)
    
    def gen_sign(self, timestamp, secret):
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign
