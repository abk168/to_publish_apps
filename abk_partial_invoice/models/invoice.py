# -*- coding: utf-8 -*-
"""
This module extends invoice functionality with custom advance payment handling and deposit logic.
"""
# pylint: disable=import-error,too-few-public-methods


from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import format_date, frozendict


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    abk_description_new = fields.Char(string="Description")


class AccountMove(models.Model):
    _inherit = 'account.move'

    abk_invoiced_percentage = fields.Float(string="Invoiced %", copy=False)
    abk_receive_data = fields.Date("Receive Date")
    abk_is_deposit = fields.Boolean("Deposit", default=False)
    abk_less_deposit = fields.Float(string="Less Deposit", copy=False)
    abk_dn_no = fields.Many2one('stock.picking', string="DN No")

    sale_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        compute='_compute_sale_id_from_lines',
        store=True,
    )

    abk_sales_order = fields.Char(
        string="Sales Order",
        compute="_compute_sales_order_names",
        store=True,
        readonly=False
    )

    def _compute_sales_order_names(self):
        for move in self:
            sale_order_names = set()
            for so in move.invoice_line_ids.mapped('sale_line_ids.order_id'):
                if so.name:
                    sale_order_names.add(so.name)

            move.abk_sales_order = ', '.join(sale_order_names) if sale_order_names else ''

    abk_related_stock_moves = fields.One2many(
        'stock.move', 'abk_related_move_id', 'Related Stock Move'
    )

    @api.depends('invoice_line_ids.sale_line_ids.order_id')
    def _compute_sale_id_from_lines(self):
        for move in self:
            sale_orders = move.invoice_line_ids.mapped('sale_line_ids.order_id')
            move.sale_id = sale_orders[0] if sale_orders else False

    @api.onchange('abk_dn_no')
    def _onchange_related_ids(self):
        for rec in self:
            if rec.abk_dn_no:
                related_moves = self.env['stock.move'].sudo().search([
                    ('picking_id', '=', rec.abk_dn_no.id)
                ])
                related_moves.write({'abk_related_move_id': rec.id})

    @api.depends('invoice_line_ids.sale_line_ids.order_id.name')
    def _compute_sales_order_names(self):
        for move in self:
            names = move.invoice_line_ids.mapped('sale_line_ids.order_id.name')
            move.abk_sales_order = ', '.join(filter(None, names))

    def action_update_receive_date(self):
        for rec in self:
            rec.abk_receive_data = fields.Date.today()

    def button_cancel(self):
        super().button_cancel()

        # Reset invoiced flag on related picking
        pickings = self.env['stock.picking'].search([('abk_inv_ref', '=', self.id)])
        pickings.write({'abk_is_invoiced': False, 'abk_inv_ref': False})

        for record in self:
            sale_order_ref = record.abk_sales_order
            if not sale_order_ref:
                continue

            sale_order = self.env['sale.order'].search([('name', '=', sale_order_ref)], limit=1)
            if not sale_order:
                continue

            # Find latest active deposit invoice
            active_deposit = self.env['account.move'].search([
                ('abk_is_deposit', '=', True),
                ('state', '!=', 'cancel'),
                ('abk_sales_order', '=', sale_order_ref)
            ], order='create_date desc', limit=1)

            if active_deposit:
                sale_order.abk_invoiced_percentage = active_deposit.abk_invoiced_percentage
            else:
                sale_order.abk_invoiced_percentage = 0.0


class AdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    advance_payment_method = fields.Selection(
        selection=[
            ('delivered', "Regular invoice"),
            ('percentage', "Down payment (percentage)"),
            ('fixed', "Down payment (fixed amount)"),
            ('custom_fixed', "Down payment (custom fixed amount)"),
        ],
        string="Create Invoice",
        default='percentage',
        required=True,
    )

    abk_fixed_amount = fields.Float(string="Custom Fixed Value")
    abk_amount = fields.Float(string="Previous Percentage value")
    abk_picking_id = fields.Many2one('stock.picking', string='Delivery')
    abk_amount_to_invoice = fields.Monetary(string="Delivered Amount to invoice")
    abk_picking_ids = fields.Many2many(
        'stock.picking', 'model_stock_picking_rel', 'model_id', 'picking_id', string='Deliveries'
    )

    @api.onchange('advance_payment_method')
    def get_dynamic_advance_payment_options(self):
        if self.abk_amount > 0 and self.advance_payment_method in ['delivered', 'fixed']:
            raise UserError(_(
                "You have already created a deposit invoice. "
                "Please select 'Down payment (percentage)' or 'Down payment (custom fixed amount)'."
            ))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self._context.get('active_id')
        if self._context.get('active_model') == 'sale.order' and active_id:
            order = self.env['sale.order'].browse(active_id)
            if 'abk_amount' in fields_list:
                res['abk_amount'] = order.abk_invoiced_percentage
            if 'abk_picking_ids' in fields_list:
                pickings = self.env['stock.picking'].search([
                    ('sale_id', '=', order.id),
                    ('abk_is_invoiced', '=', False),
                    ('state', 'in', ('done', 'assigned', 'confirmed'))
                ])
                res['abk_picking_ids'] = [(6, 0, pickings.ids)]
        return res

    @api.onchange('abk_picking_id')
    def _onchange_abk_picking_id(self):
        if self.abk_amount > 0:
            self.advance_payment_method = 'custom_fixed'

    abk_picking_id_domain = fields.Char(
        compute='_compute_abk_picking_id_domain',
        readonly=True,
    )

    @api.depends('abk_picking_ids')
    def _compute_abk_picking_id_domain(self):
        for record in self:
            if record.abk_picking_ids:
                valid = record.abk_picking_ids.filtered(lambda p: p.state != 'cancel')
                record.abk_picking_id_domain = [('id', 'in', valid.ids)]
            else:
                record.abk_picking_id_domain = [('id', '=', False)]

    @api.onchange('abk_picking_id', 'advance_payment_method')
    def _compute_abk_invoice_amounts(self):
        for wizard in self:
            wizard.abk_amount_to_invoice = 0.0

            if not wizard.abk_picking_id:
                continue

            total = 0.0

            for move in wizard.abk_picking_id.move_ids_without_package:
                sol = self.env['sale.order.line'].search(
                    [('move_ids', 'in', move.id)], limit=1
                )

                if sol:
                    unit_price = sol.price_unit

                    tax_result = sol.tax_id.compute_all(
                        unit_price,
                        currency=sol.order_id.currency_id,
                        quantity=move.product_uom_qty,
                        product=sol.product_id,
                        partner=sol.order_id.partner_id,
                    )

                    total += tax_result['total_included']

            wizard.abk_fixed_amount = total

            if wizard.advance_payment_method == 'delivered':
                wizard.abk_amount_to_invoice = total

            elif wizard.advance_payment_method == 'custom_fixed':
                deduction = total * (wizard.abk_amount / 100.0)
                wizard.abk_amount_to_invoice = max(0.0, total - deduction)

    def _create_invoices(self, sale_orders):
        invoices = super()._create_invoices(sale_orders)
        order = sale_orders.ensure_one()

        for invoice in invoices:
            # Deposit invoice (percentage < 100)
            if self.advance_payment_method == 'percentage' and self.amount != 100:
                invoice.abk_invoiced_percentage = self.amount
                invoice.abk_is_deposit = True
                if order:
                    current_percentage = order.abk_invoiced_percentage or 0.0
                    order.abk_invoiced_percentage = current_percentage + self.amount

                    current_deposit = order.deposit or 0.0
                    order.deposit = current_deposit + invoice.amount_total
            elif self.advance_payment_method == 'percentage' and self.amount == 100:
                deposit_lines = invoice.invoice_line_ids.filtered(lambda l: l.is_downpayment)
                deposit_lines.unlink()

            if self.advance_payment_method in ('delivered', 'custom_fixed') and self.abk_picking_id:
                invoice.write({'abk_dn_no': self.abk_picking_id})

                total_delivered = 0.0
                for move in self.abk_picking_id.move_ids_without_package:
                    sol = self.env['sale.order.line'].search([('move_ids', 'in', move.id)], limit=1)
                    if sol:
                        price = sol.price_unit * (1 - (sol.discount or 0.0) / 100)
                        total_delivered += move.product_uom_qty * price

                if order.abk_invoiced_percentage > 0:
                    invoice.abk_less_deposit = total_delivered * (order.abk_invoiced_percentage / 100)

                self.abk_picking_id.write({
                    'abk_is_invoiced': True,
                    'abk_inv_ref': invoice.id
                })

            invoice.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': invoice, 'origin': order},
                subtype_xmlid='mail.mt_note',
            )
            order.message_post(
                body=_("Invoice %s has been created", invoice._get_html_link()),
            )

        return invoices

    def _prepare_down_payment_lines_values(self, order):
        """ Create one down payment line per tax or unique taxes combination.
            Apply the tax(es) to their respective lines.
        """
        self.ensure_one()

        if self.advance_payment_method == 'percentage':
            percentage = self.amount / 100
        else:
            if self.abk_fixed_amount:
                percentage = (self.abk_fixed_amount * (
                        1 - (self.abk_amount / 100))) / order.amount_total if order.amount_total else 1
            else:
                percentage = self.fixed_amount / order.amount_total if order.amount_total else 1

        order_lines = order.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment)
        base_downpayment_lines_values = self._prepare_base_downpayment_line_values(order)

        tax_base_line_dicts = [
            line._convert_to_tax_base_line_dict(
                analytic_distribution=line.analytic_distribution,
                handle_price_include=False
            )
            for line in order_lines
        ]
        computed_taxes = self.env['account.tax']._compute_taxes(tax_base_line_dicts)
        down_payment_values = []

        for line, tax_repartition in computed_taxes['base_lines_to_update']:
            taxes = line['taxes'].flatten_taxes_hierarchy()
            fixed_taxes = taxes.filtered(lambda tax: tax.amount_type == 'custom_fixed') if taxes.filtered(
                lambda tax: tax.amount_type == 'custom_fixed') else taxes.filtered(
                lambda tax: tax.amount_type == 'fixed')
            down_payment_values.append([
                taxes - fixed_taxes,
                line['analytic_distribution'],
                tax_repartition['price_subtotal']
            ])
            for fixed_tax in fixed_taxes:
                if fixed_tax.price_include:
                    continue

                if fixed_tax.include_base_amount:
                    pct_tax = taxes[list(taxes).index(fixed_tax) + 1:] \
                        .filtered(lambda t: t.is_base_affected and t.amount_type != 'custom_fixed')
                    if not pct_tax:
                        pct_tax = taxes[list(taxes).index(fixed_tax) + 1:] \
                            .filtered(lambda t: t.is_base_affected and t.amount_type != 'fixed')
                else:
                    pct_tax = self.env['account.tax']

                if fixed_tax.invoice_amount:
                    down_payment_values.append([
                        pct_tax,
                        line['analytic_distribution'],
                        line['quantity'] * fixed_tax.invoice_amount
                    ])
                else:
                    down_payment_values.append([
                        pct_tax,
                        line['analytic_distribution'],
                        line['quantity'] * fixed_tax.amount
                    ])

        # NOW define downpayment_line_map here
        downpayment_line_map = {}
        for tax_id, analytic_distribution, price_subtotal in down_payment_values:
            grouping_key = frozendict({
                'tax_id': tuple(sorted(tax_id.ids)),
                'analytic_distribution': analytic_distribution,
            })
            downpayment_line_map.setdefault(grouping_key, {
                **base_downpayment_lines_values,
                **grouping_key,
                'product_uom_qty': 0.0,
                'price_unit': 0.0,
            })
            downpayment_line_map[grouping_key]['price_unit'] += price_subtotal

        # Apply percentage
        for key in downpayment_line_map:
            downpayment_line_map[key]['price_unit'] = \
                order.currency_id.round(downpayment_line_map[key]['price_unit'] * percentage)

        # Add delivery name if applicable
        if self.abk_picking_id:
            for values in downpayment_line_map.values():
                values['name'] = self.abk_picking_id.name

        return list(downpayment_line_map.values())

    def _prepare_base_downpayment_line_values(self, order):
        self.ensure_one()
        if self.abk_picking_id:
            return {
                'name': self.abk_picking_id.name,
                'product_uom_qty': 0.0,
                'order_id': order.id,
                'discount': 0.0,
                'product_id': self.product_id.id,
                'is_downpayment': True,
                'sequence': (order.order_line[-1].sequence + 1) if order.order_line else 10,
            }
        else:
            return {
                'name': _('Down Payment: %s', format_date(self.env, fields.Date.today())),
                'product_uom_qty': 0.0,
                'order_id': order.id,
                'discount': 0.0,
                'product_id': self.product_id.id,
                'is_downpayment': True,
                'sequence': (order.order_line[-1].sequence + 1) if order.order_line else 10,
            }
