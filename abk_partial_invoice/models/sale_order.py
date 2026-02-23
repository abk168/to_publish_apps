# -*- coding: utf-8 -*-
"""
This module extends invoice functionality with custom advance payment handling and deposit logic.
"""
# pylint: disable=import-error,too-few-public-methods

from odoo import models, fields, api, _
from odoo.fields import Command


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    abk_invoiced_percentage = fields.Float(string="Invoiced %", copy=False)
    deposit = fields.Float(string="Deposit Amount", copy=False)

    def update_invoiced_percentage(self):
        """for imported sale orders which are partially paid"""
        sale_orders = self.search([
            ('x_studio_sc_number', '!=', False),
            ('payment_status', '=', 'partial_paid'),
        ])
        for order in sale_orders:
            total_invoiced = sum(
                invoice.amount_total
                for invoice in order.invoice_ids
                if invoice.state in ('draft', 'posted')  # 🔥 include draft
            )
            total_order_amount = order.amount_total
            if total_order_amount > 0:
                invoiced_percentage = (total_invoiced / total_order_amount) * 100
            else:
                invoiced_percentage = 0.0
            order.abk_invoiced_percentage = invoiced_percentage
        return True


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends(
        'invoice_lines.move_id.state',
        'invoice_lines.price_total'
    )
    def _compute_amount_invoiced(self):
        for line in self:
            amount = 0.0

            invoice_lines = line.invoice_lines.filtered(
                lambda l: l.move_id.state in ('draft', 'posted')
            )

            for inv_line in invoice_lines:
                amount += inv_line.price_total

            line.amount_invoiced = amount

    def _prepare_invoice_line(self, **optional_values):
        self.ensure_one()
        res = {
            'display_type': self.display_type or 'product',
            'sequence': self.sequence,
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_uom.id,
            'quantity': self.qty_to_invoice,
            'discount': self.discount,
            'price_unit': self.price_unit,
            'tax_ids': [Command.set(self.tax_id.ids)],
            'sale_line_ids': [Command.link(self.id)],
            'is_downpayment': self.is_downpayment,
            'abk_description_new': self.product_id.name,
        }

        self._set_analytic_distribution(res, **optional_values)

        if optional_values:
            if self.product_id.name == 'Down payment':
                optional_values = {'name': self.name, 'quantity': 1.0}
                res.update(optional_values)
            else:
                res.update(optional_values)

        if self.display_type:
            res['account_id'] = False

        return res


class SaleOrderDiscount(models.TransientModel):
    _inherit = 'sale.order.discount'

    def _prepare_discount_product_values(self):
        self.ensure_one()
        return {
            'name': _('Discount'),
            'type': 'product',
            'invoice_policy': 'order',
            'list_price': 0.0,
            'company_id': self.company_id.id,
            'taxes_id': None,
        }