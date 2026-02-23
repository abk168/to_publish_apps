# -*- coding: utf-8 -*-
"""
This module extends invoice functionality with custom advance payment handling and deposit logic.
"""
# pylint: disable=import-error,too-few-public-methods


from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    abk_invoiced_percentage = fields.Float(string="Invoiced %", copy=False)
    deposit = fields.Float(string="Deposit Amount", copy=False)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_invoice_line(self, **optional_values):
        self.ensure_one()
        res = super()._prepare_invoice_line(**optional_values)
        res.update({
            'abk_description_new': self.product_id.name,
        })
        if self.product_id.name == 'Down payment':
            res.update({'name': self.name, 'quantity': 1.0})
        return res
