from odoo import models, fields, api
import requests
import json

HEADERS = {
    'Content-Type': 'application/json; charset=utf-8'
}

class LarkWebHook(models.Model):
    _name = "lark.web.hook"
    _description = "Lark Web Hook"

    name = fields.Char(string="Hook Name", required=True)
    short_name = fields.Char(string="Short Name", required=True)
    hook_url = fields.Char(string="Hook URL", required=True)
    hook_url_basic_key = fields.Char(string="Hook URL Basic Key", required=False, password=True)
    is_active = fields.Boolean(string="Is Active", default=True)

    def send_hook_request(self, payload):
        if not self.is_active:
            return False
        return self.call_request(payload)

    def call_request(self, payload):
        headers = HEADERS
        if self.hook_url_basic_key:
            headers['Authorization'] = f"Basic {self.hook_url_basic_key}"

        response = requests.post(self.hook_url, data=json.dumps(payload), headers=headers)
        if response.status_code == 200:
            return True
        return False
    
    def get_lark_job_from_short_name(self, short_name):
        return self.search([('short_name', '=', short_name), ('is_active', '=', True)], limit=1)