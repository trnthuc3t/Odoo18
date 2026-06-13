{
    "name": "Tour Sales Order",
    "summary": "Customize Sales Order for Tour",
    "description": """
        Module customize lại Sales Order của Odoo.
        Được tách ra từ module tour_product_sync.
    """,
    "version": "1.0.0",
    "category": "Sales",
    "author": "Tour Team",
    "depends": [
        "sale",
        "sale_project",
        "account",
        "purchase",
    ],
    "data": [
        "views/sale_order.xml",
        "views/sale_order_line_views.xml",
        "views/product_template_views.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
        ],
        "web.assets_frontend": [
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3"
}
