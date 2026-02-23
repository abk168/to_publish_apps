# -*- coding: utf-8 -*-
"""
This module extends invoice functionality with custom advance payment handling and deposit logic.
"""
# pylint: disable=import-error,too-few-public-methods
from odoo import models, fields


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_invoiced = fields.Boolean(
        default=False,
        string='Invoiced', readonly=True
    )

    inv_ref = fields.Char(
        string='Invoice Reference', readonly=True
    )

    sale_id = fields.Many2one('sale.order', string='Sale Order')






