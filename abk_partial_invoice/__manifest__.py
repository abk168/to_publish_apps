# -*- coding: utf-8 -*-
###################################################################################
#
#  Aboutknowledge (Hong Kong) Limited.
#
#  Copyright (C) 2022-TODAY Aboutknowledge (Hong Kong) Limited
#  (<https://www.aboutknowledge.com>).
#  Author: Aboutknowledge (Hong Kong) Limited
#  (<https://www.aboutknowledge.com/>)
#
###################################################################################

{
    'name': 'Custom Fixed Amount Partial Invoice',
    'version': '18.0.1.0.0',
    'author': 'Aboutknowledge (Hong Kong) Limited',
    'company': 'Aboutknowledge (Hong Kong) Limited',
    'maintainer': 'Aboutknowledge (Hong Kong) Limited',
    'website': 'https://www.aboutknowledge.com/',
    'category': 'Accounting/Invoicing',
    'summary': 'Create partial invoices using fixed amounts or percentages and invoice from delivery orders.',
    'description': """
Custom Fixed Amount Partial Invoice for Odoo 18
==============================================

This module allows users to generate partial invoices from Sale Orders
using a custom fixed amount or a percentage of the total order value.
It also supports creating invoices directly from Delivery Orders (DN)

Key Features:
-------------
- Create partial invoices using fixed amount or percentage
- Generate invoices directly from Delivery Orders (DN)
- Supports multiple delivery orders per Sale Order
- Prevents over-invoicing automatically
- Full integration with Sales, Inventory, and Accounting
- Multi-company support
- Access control using standard Odoo security groups
- Compatible with Odoo 18  Enterprise
""",
    'depends': [
        'base',
        'sale',
        'sale_management',
        'accountant',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/invoice.xml',
        'views/sale_order.xml',
        'views/stock_picking.xml'
    ],
    'images': [
        'static/description/banner.png',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': True,
    'price': 29.99,
    'currency': 'USD',
}
