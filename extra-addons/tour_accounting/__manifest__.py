{
    "name": "Tour Accounting",
    "summary": "Customizations for Accounting",
    "description": "",
    "version": "1.0.0",
    "category": "Accounting",
    "author": "thuctt",
    "depends": [
        "account",
        "base",
        "payment",
        "sale"
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/account_move.xml",
        "views/payment_provider.xml",
        "views/payment_checkout.xml",
        "views/report_invoice_combo_mc.xml",
    ],
    "assets": {
        "web.assets_frontend": [
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3"
}
