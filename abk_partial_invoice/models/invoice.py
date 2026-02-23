# -*- coding: utf-8 -*-
"""
This module extends invoice functionality with custom advance payment handling and deposit logic.
"""
# pylint: disable=import-error,too-few-public-methods


from odoo import models, fields, api, SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.tools import format_date, frozendict


class AccountMove(models.Model):
    _inherit = 'account.move'

    abk_invoiced_percentage = fields.Float(string="Invoiced %", copy=False)
    abk_total_invoiced_percentage = fields.Float(string="Total Invoiced %", copy=False)
    receive_data_abk = fields.Date("Receive Date")
    is_deposit = fields.Boolean("Deposit", default=False)
    less_deposit = fields.Float(string="Less Deposit", copy=False)
    is_custom_fixed = fields.Boolean("Custom Deposit", default=False)
    abk_dn_no = fields.Many2one('stock.picking', string="DN No")
    sale_id = fields.Many2one('sale.order', string='Sale Order')
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

    def action_update_receive_date(self):
        for rec in self:
            rec.receive_data_abk = fields.Datetime.now()

    def button_cancel(self):

        super(AccountMove, self).button_cancel()
        if self.sale_id and self.sale_id.picking_ids:
            rec = self.env['stock.picking'].search([('inv_ref', '=', self.id)])
            if rec.is_invoiced:
                rec.is_invoiced = False
            for record in self:
                sale_order_ref = record.abk_sales_order
                if sale_order_ref:
                    sale_order = self.env['sale.order'].search([('name', '=', sale_order_ref)], limit=1)

                    deposit_invoices = self.env['account.move'].search([
                        ('is_deposit', '=', True),
                        ('abk_sales_order', '=', sale_order_ref)], order='create_date desc')

                    if deposit_invoices:
                        last_deposit_invoice = deposit_invoices[0]
                    else:
                        last_deposit_invoice = None

                    active_deposit_invoices = self.env['account.move'].search([
                        ('is_deposit', '=', True),
                        ('state', '!=', 'cancel'),
                        ('abk_sales_order', '=', sale_order_ref)
                    ], order='create_date desc')
                    if sale_order and last_deposit_invoice and last_deposit_invoice.state == 'cancel':
                        if active_deposit_invoices:
                            last_active_deposit_invoice = active_deposit_invoices[0]
                            sale_order.write({
                                'abk_invoiced_percentage': last_active_deposit_invoice.abk_invoiced_percentage
                            })
                if record.abk_invoiced_percentage:
                    valid_invoices = self.env['account.move'].search([
                        ('state', '!=', 'cancel'),
                        ('is_deposit', '=', False),
                        ('abk_sales_order', '=', sale_order_ref)
                    ])
                    for inv in valid_invoices:
                        if inv.abk_total_invoiced_percentage == 100:
                            inv.abk_total_invoiced_percentage = inv.abk_total_invoiced_percentage - record.abk_invoiced_percentage

    abk_total_in_invoice = fields.Monetary(
        string='Total in Invoice',
        compute='_compute_total_in_invoice',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('invoice_line_ids.price_subtotal')
    def _compute_total_in_invoice(self):
        for move in self:
            move.abk_total_in_invoice = sum(move.invoice_line_ids.mapped('price_subtotal'))


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    abk_description_new = fields.Char(string="Description", compute="_compute_abk_description", readonly=False,
                                      store=True)

    @api.depends('product_id')
    def _compute_abk_description(self):
        for line in self:
            if line.product_id:
                line.abk_description_new = line.product_id.name
            else:
                line.abk_description_new = ''


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
        help="A standard invoice is issued with all the order lines ready for invoicing,"
             "according to their invoicing policy (based on ordered or delivered quantity).")

    abk_fixed_amount = fields.Float(
        string="Custom Fixed Value",
        help="The fixed amount to be invoiced")
    abk_amount = fields.Float(
        string="Previous Percentage value",
        help="The fixed amount to be invoiced")
    abk_picking_id = fields.Many2one(
        'stock.picking',
        string='Delivery',
    )
    abk_amount_to_invoice = fields.Monetary(
        string="Delivered Amount to invoice",
        help="The delivered amount to invoice  - Confirmed Down Payments.")
    abk_picking_ids = fields.Many2many(
        'stock.picking', 'model_stock_picking_rel', 'model_id', 'picking_id', string='Deliveries'
    )

    @api.onchange('advance_payment_method')
    def get_dynamic_advance_payment_options(self):
        for rec in self:
            if rec.abk_amount > 0:
                if rec.advance_payment_method in ['delivered', 'fixed']:
                    raise UserError(_(
                        "You have already created deposit invoice, Please select 'Down payment (percentage)' and 'Down payment (custom fixed amount)' to create a invoice."
                    ))

    @api.model
    def default_get(self, fields):
        res = super(AdvancePaymentInv, self).default_get(fields)

        if 'abk_amount' in fields and not res.get('abk_amount') and self._context.get(
                'active_model') == 'sale.order' and self._context.get('active_id'):
            sale_order = self.env['sale.order'].browse(self._context['active_id'])
            res['abk_amount'] = sale_order.abk_invoiced_percentage
        if 'abk_picking_ids' in fields:
            if self._context.get('active_model') == 'sale.order' and self._context.get(
                    'active_id'):
                sale_order = self.env['sale.order'].browse(self._context['active_id'])
                pickings = self.env['stock.picking'].search(
                    [('sale_id', '=', sale_order.id), ('is_invoiced', '=', False)])
                res['abk_picking_ids'] = [(6, 0, pickings.ids)]
        return res

    @api.onchange('abk_picking_id')
    def _onchange_abk_picking_id(self):
        if self.abk_amount != 0.0:
            self.advance_payment_method = 'custom_fixed'

    abk_picking_id_domain = fields.Char(
        compute='_compute_abk_picking_id_domain',
        string='Picking ID Domain', readonly=False
    )

    @api.depends('abk_picking_ids')
    def _compute_abk_picking_id_domain(self):
        for record in self:
            if record.abk_picking_ids:
                deliveries = record.abk_picking_ids.filtered(
                    lambda p: p.state != 'cancel' and p.picking_type_id.code == 'outgoing'
                )
                record.abk_picking_id_domain = str([('id', 'in', deliveries.ids)])
            else:
                record.abk_picking_id_domain = str([('id', '=', False)])

    def _get_abk_picking_id_domain(self):
        self.ensure_one()
        if self.abk_picking_ids:
            return [('id', 'in', self.abk_picking_ids.ids)]
        return []

    @api.onchange('abk_picking_id', 'advance_payment_method')
    def _compute_abk_invoice_amounts(self):
        for wizard in self:
            delivery = wizard.abk_picking_id
            if wizard.abk_picking_id and wizard.advance_payment_method == 'delivered':

                stock_moves = self.env['stock.move'].search([('picking_id', '=', delivery.id)])
                done_qty_by_product = {}
                unit_price_by_product = {}
                total_amount_by_product = {}
                for picking in wizard.abk_picking_ids:
                    stock_moves = self.env['stock.move'].search(
                        [('picking_id', '=', picking.ids), ('picking_id', '=', delivery.id)])
                    for move in stock_moves:
                        product = move.product_id
                        done_qty = move.product_uom_qty
                        if product.id not in done_qty_by_product:
                            done_qty_by_product[product.id] = 0
                        done_qty_by_product[product.id] += done_qty

                        sale_order_line = self.env['sale.order.line'].search([('move_ids', 'in', move.id)], limit=1)
                        if sale_order_line:
                            unit_price_by_product[product.id] = sale_order_line.price_unit
                for product_id in done_qty_by_product:
                    done_qty = done_qty_by_product[product_id]
                    unit_price = unit_price_by_product.get(product_id, 0)
                    total_amount_by_product[product_id] = done_qty * unit_price

                total_amount = sum(total_amount_by_product.values())
                self.abk_fixed_amount = total_amount
                wizard.abk_amount_to_invoice = total_amount - wizard.amount_invoiced
                wizard.amount_to_invoice = wizard.abk_amount_to_invoice
            elif wizard.advance_payment_method == 'custom_fixed' and self.abk_amount and self.abk_picking_id:
                done_qty_by_sale_order_line = {}
                done_qty_by_product = {}
                unit_price_by_sale_order_line = {}
                discount_by_sale_order_line = {}
                total_amount_sale_order_line = {}

                for picking in wizard.abk_picking_ids:
                    stock_moves = self.env['stock.move'].search(
                        [('picking_id', '=', picking.ids), ('picking_id', '=', delivery.id)])
                    for move in stock_moves:
                        product = move.product_id
                        done_qty = move.product_uom_qty

                        if product.id not in done_qty_by_product:
                            done_qty_by_product[product.id] = 0
                        done_qty_by_product[product.id] += done_qty

                        sale_order_line = self.env['sale.order.line'].search([('move_ids', 'in', move.id)], limit=1)
                        if sale_order_line:
                            unit_price_by_sale_order_line[sale_order_line.id] = sale_order_line.price_unit
                            discount_by_sale_order_line[sale_order_line.id] = sale_order_line.discount
                            done_qty_by_sale_order_line[sale_order_line.id] = done_qty_by_product[product.id]
                for line in done_qty_by_sale_order_line:
                    done_qty = done_qty_by_sale_order_line[line]
                    unit_price = unit_price_by_sale_order_line.get(line, 0)
                    sale_line = self.env['sale.order.line'].browse(line)

                    tax_result = sale_line.tax_id.compute_all(
                        unit_price,
                        currency=sale_line.order_id.currency_id,
                        quantity=done_qty,
                        product=sale_line.product_id,
                        partner=sale_line.order_id.partner_id,
                    )


                    total_amount_sale_order_line[line] = tax_result['total_included']

                total_amount = sum(total_amount_sale_order_line.values())
                self.abk_fixed_amount = total_amount
                sale_order = self.env['sale.order'].search([('picking_ids', 'in', delivery.id)], limit=1)
                if sale_order:
                    down_payments = self.env['account.move'].search([
                        ('invoice_origin', '=', sale_order.name),
                        ('move_type', '=', 'out_invoice'),
                    ])
                    total_down_payment = sum(down_payments.mapped('amount_total'))
                    less_discount = total_amount * (sale_order.abk_invoiced_percentage) / 100
                    wizard.abk_amount_to_invoice = wizard.abk_fixed_amount
                    wizard.amount_to_invoice = wizard.abk_amount_to_invoice - less_discount

    @api.onchange('advance_payment_method')
    def _onchange_advance_payment_method(self):
        res = super()._onchange_advance_payment_method()
        if self.advance_payment_method == 'custom_fixed':
            self.amount_to_invoice = self.abk_amount_to_invoice
        return res

    def _create_invoices(self, sale_orders):
        invoices = super(AdvancePaymentInv, self)._create_invoices(sale_orders)
        self.sale_order_ids.ensure_one()
        self = self.with_company(self.company_id)
        order = self.sale_order_ids
        for invoice in invoices:

            if self.advance_payment_method == 'percentage':
                if self.amount != 100:
                    invoice.abk_invoiced_percentage = self.amount

                    previous_invoices = self.env['account.move'].search([
                        ('id', '!=', invoice.id),
                        ('state', 'in', ['draft', 'posted']),
                        ('invoice_origin', '=', order.name),
                        ('abk_invoiced_percentage', '!=', 0),
                    ])
                    cumulative_percentage = sum(previous_invoices.mapped('abk_invoiced_percentage')) + self.amount
                    invoice.abk_total_invoiced_percentage = cumulative_percentage

                    invoice.is_deposit = not previous_invoices

                    order.abk_invoiced_percentage = self.amount
                    order.deposit = invoice.amount_total


                else:
                    deposit_lines = invoice.invoice_line_ids.filtered(
                        lambda line: line.product_id.name == 'Deposit'
                    )
                    deposit_lines.unlink()
                    return sale_orders._create_invoices(
                        final=self.deduct_down_payments,
                        grouped=not self.consolidated_billing
                    )

            invoice = invoice.sudo(self.env.su)
            invoice.write({'abk_dn_no': self.abk_picking_id})
            amount_total = 0.0
            if invoice.abk_dn_no:
                total_sum = 0.0
                lines_from_move = invoice.abk_dn_no.move_ids
                sale_order = invoice.abk_dn_no.sale_id

                for line in lines_from_move:
                    matching_so_line = None
                    for sol in sale_order.order_line:
                        if sol.product_id.id == line.product_id.id:
                            matching_so_line = sol
                            break

                    if matching_so_line:
                        line_total = (line.product_uom_qty * matching_so_line.price_unit) * (
                                1 - (matching_so_line.discount or 0) / 100
                        )
                        total_sum += line_total

                amount_total = total_sum

            if invoice.abk_dn_no and invoice.abk_dn_no.sale_id:
                sale_id = invoice.abk_dn_no.sale_id
                if sale_id.abk_invoiced_percentage > 0:
                    invoice.less_deposit = amount_total * (sale_id.abk_invoiced_percentage) / 100
            invoice = invoice.sudo(self.env.su)

            poster = self.env.user._is_internal() and self.env.user.id or SUPERUSER_ID
            invoice.with_user(poster).message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': invoice, 'origin': order},
                subtype_xmlid='mail.mt_note',
            )

            title = _("Down payment invoice")
            order.with_user(poster).message_post(
                body=_("%s has been created", invoice._get_html_link(title=title)),
            )
            invoice.write({'sale_id': order.id})
            if self.abk_picking_id:
                self.abk_picking_id.write({'is_invoiced': True, 'inv_ref': invoice.id})

        return invoices

    def _prepare_down_payment_lines_values(self, order):
        self.ensure_one()
        AccountTax = self.env['account.tax']

        if self.advance_payment_method == 'percentage':
            ratio = self.amount / 100
        else:
            if self.abk_fixed_amount:
                ratio = (
                        (self.abk_fixed_amount * (1 - (self.abk_amount / 100)))
                        / order.amount_total
                ) if order.amount_total else 1
            else:
                ratio = self.fixed_amount / order.amount_total if order.amount_total else 1

        order_lines = order.order_line.filtered(
            lambda l: not l.display_type and not l.is_downpayment
        )

        down_payment_values = []

        for line in order_lines:
            base_line_values = line._prepare_base_line_for_taxes_computation(
                special_mode='total_excluded'
            )

            product_account = line.product_id.product_tmpl_id.get_product_accounts(
                fiscal_pos=order.fiscal_position_id
            )
            account = product_account.get('downpayment') or product_account.get('income')

            AccountTax._add_tax_details_in_base_line(base_line_values, order.company_id)
            tax_details = base_line_values['tax_details']

            taxes = line.tax_id.flatten_taxes_hierarchy()

            fixed_taxes = taxes.filtered(
                lambda tax: tax.amount_type in ('custom_fixed', 'fixed')
            )

            down_payment_values.append([
                taxes - fixed_taxes,
                base_line_values['analytic_distribution'],
                tax_details['raw_total_excluded_currency'],
                account,
            ])

            for fixed_tax in fixed_taxes:

                for fixed_tax in fixed_taxes:
                    if fixed_tax.price_include:
                        continue

                    if fixed_tax.include_base_amount:
                        pct_tax = taxes.filtered(
                            lambda t: t.is_base_affected and t.amount_type not in ('custom_fixed', 'fixed')
                        )
                    else:
                        pct_tax = self.env['account.tax']

                    quantity = base_line_values.get('quantity', line.product_uom_qty)

                    if getattr(fixed_tax, 'invoice_amount', False):
                        amount = quantity * fixed_tax.invoice_amount
                    else:
                        amount = quantity * fixed_tax.amount

                    down_payment_values.append([
                        pct_tax,
                        base_line_values['analytic_distribution'],
                        amount,
                        account,
                    ])

        downpayment_line_map = {}
        analytic_map = {}

        base_downpayment_lines_values = self._prepare_base_downpayment_line_values(order)

        for tax_id, analytic_distribution, price_subtotal, account in down_payment_values:

            grouping_key = frozendict({
                'tax_id': tuple(sorted(tax_id.ids)),
                'account_id': account,
            })

            downpayment_line_map.setdefault(grouping_key, {
                **base_downpayment_lines_values,
                'tax_id': grouping_key['tax_id'],
                'product_uom_qty': 0.0,
                'price_unit': 0.0,
            })

            downpayment_line_map[grouping_key]['price_unit'] += price_subtotal

            if analytic_distribution:
                analytic_map.setdefault(grouping_key, [])
                analytic_map[grouping_key].append(
                    (price_subtotal, analytic_distribution)
                )

        lines_values = []
        accounts = []

        for key, line_vals in downpayment_line_map.items():

            if order.currency_id.is_zero(line_vals['price_unit']):
                continue

            if analytic_map.get(key):
                line_analytic_distribution = {}
                for price_subtotal, account_distribution in analytic_map[key]:
                    for acc, distribution in account_distribution.items():
                        line_analytic_distribution.setdefault(acc, 0.0)
                        line_analytic_distribution[acc] += (
                                price_subtotal / line_vals['price_unit'] * distribution
                        )
                line_vals['analytic_distribution'] = line_analytic_distribution

            line_vals['price_unit'] = order.currency_id.round(
                line_vals['price_unit'] * ratio
            )

            if self.abk_picking_id:
                line_vals['name'] = self.abk_picking_id.name

            lines_values.append(line_vals)
            accounts.append(key['account_id'])

        return lines_values, accounts

    def _prepare_base_downpayment_line_values(self, order):
        self.ensure_one()
        context = {'lang': order.partner_id.lang}
        if self.abk_picking_id:
            so_values = {
                'name': _(
                    self.abk_picking_id.name
                ),
                'product_uom_qty': 0.0,
                'order_id': order.id,
                'discount': 0.0,

                'is_downpayment': True,
                'sequence': order.order_line and order.order_line[-1].sequence + 1 or 10,
            }
        else:
            so_values = {
                'name': _(
                    'Down Payment: %(date)s ', date=format_date(self.env, fields.Date.today())
                ),
                'product_uom_qty': 0.0,
                'order_id': order.id,
                'discount': 0.0,

                'is_downpayment': True,
                'sequence': order.order_line and order.order_line[-1].sequence + 1 or 10,
            }
        del context
        return so_values
