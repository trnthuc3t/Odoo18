{
    "name": "Tour Product",
    "summary": "Customizations products",
    "description": "",
    "version": "1.0.0",
    "category": "Products",
    "author": "thuctt",
    "depends": [
        "sale",
        "product",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/product_template.xml",
        "views/product_product.xml",
        "views/tour_website.xml",
    ],
    "assets": {
        "web.assets_backend": [
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3"
}
