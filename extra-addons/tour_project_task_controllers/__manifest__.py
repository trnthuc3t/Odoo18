{
    "name": "Tour Project Task Controllers",
    "summary": "Automatic task generation from invoices with task templates",
    "description": """
        Task Template Management System
        ================================
        - Auto-generate project tasks when invoice is paid or guaranteed
        - Task templates with dependencies and scheduling
        - Working hours integration
        - Mentor and manager assignment
        - Product-based task automation for travel/tourism industry
    """,
    "version": "1.0.0",
    "category": "Sales/Project",
    "author": "thuctt",
    "depends": [
        "sale",
        "sale_project",
        "project",
        "account",
        "hr",
        "mail",
        "resource",
        "tour_project",
        "tour_lark_connector",
        "tour_n8n_connector",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/task_template_views.xml",
        "views/account_move_views.xml",
        "views/project_task_views.xml",
        "views/sale_order.xml",
        "views/project_views.xml",
        "wizards/create_task_manual_wizard.xml",
        "wizards/export_vat_wizard.xml",
        # "views/order_action.xml",
    ],
    "assets": {
        "web.assets_backend": [
        ],
    },
    "application": True,
    "installable": True,
    "license": "LGPL-3"
}
