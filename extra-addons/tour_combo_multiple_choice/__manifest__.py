{
    "name": "Tour Product Combo Multiple Choice",
    "summary": "Customizations product combo multiple choice",
    "description": "",
    "version": "1.0.0",
    "category": "Product",
    "author": "thuctt",
    "depends": [
        "sale",
        "product",
    ],
    "data": [
        "views/product_template.xml",
        "views/product_combo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tour_combo_multiple_choice/static/src/js/day_tour_configurator.js",
            "tour_combo_multiple_choice/static/src/js/combo_multiple_selector.js",
            "tour_combo_multiple_choice/static/src/xml/day_tour_configurator_templates.xml",
            "tour_combo_multiple_choice/static/src/xml/combo_multiple_selector_templates.xml",
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3"
}
