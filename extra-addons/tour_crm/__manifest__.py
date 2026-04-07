{
    "name": "Tour CRM Lead",
    "summary": "Customizations for CRM Lead",
    "description": "",
    "version": "1.0.1",
    "category": "Sales",
    "author": "thuctt",
    "depends": [
        "sale",
        "sale_crm",
        "crm",
        "base"
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/crm_lead.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tour_crm/static/src/js/crm_lead_product_field.js",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3"
}
