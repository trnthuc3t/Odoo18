from odoo import _, api, models, fields
from odoo.exceptions import ValidationError
from odoo.fields import Command
import json

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _prepare_combo_line_commands(self, line, index):
        linked_lines = line._get_linked_lines()
        selected_combo_items = json.loads(line.selected_combo_items)
        if (
            selected_combo_items
            and len(selected_combo_items) != len(line.product_template_id.combo_ids)
            and not line.product_template_id.is_combo_multiple_choice
            and not line.product_template_id.is_day_tour
        ):
            raise ValidationError(_(
                "The number of selected combo items must match the number of available"
                " combo choices."
            ))

        delete_commands = [Command.delete(linked_line.id) for linked_line in linked_lines]

        section_delete_commands = []
        if line.product_template_id.is_combo_multiple_choice or line.product_template_id.is_day_tour:
            for sol in self.order_line:
                if sol.display_type != 'line_note':
                    continue
                if line._origin:
                    if sol.linked_line_id.id == line._origin.id:
                        section_delete_commands.append(Command.delete(sol.id))
                elif getattr(sol, 'linked_virtual_id', False) == line.virtual_id:
                    section_delete_commands.append(Command.delete(sol.id))

        section_commands = []
        section_offset = 0
        if (line.product_template_id.is_combo_multiple_choice or line.product_template_id.is_day_tour) and selected_combo_items:
            combo_item_ids = [item['combo_item_id'] for item in selected_combo_items]
            combo_items = self.env['product.combo.item'].browse(combo_item_ids)
            combo_names = combo_items.mapped('combo_id.name')
            unique_combo_names = list(dict.fromkeys(combo_names))
            section_name = ' + '.join(unique_combo_names)

            section_commands = [Command.create({
                'display_type': 'line_note',
                'name': section_name,
                'sequence': line.sequence + 1,
                'linked_line_id': line.id if line._origin else False,
                'linked_virtual_id': line.virtual_id if not line._origin else False,
            })]
            section_offset = 1

        create_commands = []
        for item_index, combo_item in enumerate(selected_combo_items):
            combo_item_record = self.env['product.combo.item'].browse(combo_item['combo_item_id'])
            selected_qty = combo_item.get('selected_quantity') or 1
            try:
                selected_qty = max(int(selected_qty), 1)
            except Exception:
                selected_qty = 1

            if line.product_template_id.is_day_tour:
                item_qty = line.product_uom_qty
            elif line.product_template_id.is_combo_multiple_choice and combo_item_record.quantity:
                item_qty = line.product_uom_qty * combo_item_record.quantity * selected_qty
            else:
                item_qty = line.product_uom_qty * selected_qty

            create_commands.append(Command.create({
                'product_id': combo_item['product_id'],
                'product_uom_qty': item_qty,
                'combo_item_id': combo_item['combo_item_id'],
                'product_no_variant_attribute_value_ids': [
                    Command.set(combo_item['no_variant_attribute_value_ids'])
                ],
                'product_custom_attribute_value_ids': [Command.clear()] + [
                    Command.create(attribute_value)
                    for attribute_value in combo_item['product_custom_attribute_values']
                ],
                'sequence': line.sequence + section_offset + item_index + 1,
                'linked_line_id': line.id if line._origin else False,
                'linked_virtual_id': line.virtual_id if not line._origin else False,
            }))

        update_commands = [Command.update(
            order_line.id,
            {'sequence': line.sequence + len(selected_combo_items) + section_offset + line_index - index},
        ) for line_index, order_line in enumerate(
            self.order_line.filtered(lambda order_line: not order_line.combo_item_id and order_line.display_type != 'line_note')
        ) if line_index > index]

        return section_delete_commands + delete_commands + section_commands + create_commands + update_commands

    def action_expand_selected_combo_items(self):
        for index, line in enumerate(self.order_line):
            if line.product_type != 'combo' or not line.selected_combo_items:
                continue

            commands = self._prepare_combo_line_commands(line, index)
            if commands:
                self.write({'order_line': commands})
            line.write({'selected_combo_items': False})

    #kế thừa lại hàm của code core để thêm điều kiện tránh raise lỗi khi là combo multiple choice
    #code core có hàm _onchange_order_line đang hoạt động!
    @api.onchange('order_line')
    def _onchange_order_line(self):
        for index, line in enumerate(self.order_line):
            if line.product_type == 'combo' and line.selected_combo_items:
                commands = self._prepare_combo_line_commands(line, index)
                line.selected_combo_items = False
                self.order_line = commands

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    is_combo_multiple_choice = fields.Boolean(related='product_template_id.is_combo_multiple_choice', string="Is Combo Multiple Choice", store=True)
    is_day_tour = fields.Boolean(related='product_template_id.is_day_tour', string="Is Day Tour", store=True)

    def _get_combo_item_display_price(self):
        """Override to use fixed_price/lst_price + extra_price for combo items.
        For multiple choice combo: use fixed_price if set, otherwise lst_price + extra_price.
        All prices include proper currency conversion."""
        self.ensure_one()
        
        # Check if this is a multiple choice combo or day tour and has fixed_price
        combo_line = self._get_linked_line()
        if (combo_line and 
            (combo_line.product_template_id.is_combo_multiple_choice or combo_line.product_template_id.is_day_tour) and 
            self.combo_item_id.fixed_price):
            
            # Use fixed_price with currency conversion
            product_price = self.combo_item_id.fixed_price
            if self.combo_item_id.currency_id and self.currency_id and self.combo_item_id.currency_id != self.currency_id:
                product_price = self.combo_item_id.currency_id._convert(
                    from_amount=product_price,
                    to_currency=self.currency_id,
                    company=self.company_id,
                    date=self.order_id.date_order,
                )
            
            # For day tour with shared_cost_enabled: divide by customer quantity
            if (combo_line.product_template_id.is_day_tour
                    and self.combo_item_id.shared_cost_enabled
                    and combo_line.product_uom_qty > 0):
                product_price = product_price / combo_line.product_uom_qty
            
            # Add the extra prices of any `no_variant` attributes
            return product_price + self.product_id._get_no_variant_attributes_price_extra(
                self.product_no_variant_attribute_value_ids
            )
        
        # Default logic: Use product's lst_price + extra_price (both with currency conversion)
        
        # 1. Get and convert lst_price
        product_price = self.combo_item_id.product_id.lst_price
        if self.combo_item_id.currency_id and self.currency_id and self.combo_item_id.currency_id != self.currency_id:
            product_price = self.combo_item_id.currency_id._convert(
                from_amount=product_price,
                to_currency=self.currency_id,
                company=self.company_id,
                date=self.order_id.date_order,
            )
        
        # 2. Convert and add extra_price (with proper currency conversion)
        if self.combo_item_id.extra_price:
            converted_extra_price = self.env['product.combo.item'].get_extra_price_in_currency(
                combo_item_id=self.combo_item_id.id,
                target_currency_id=self.currency_id.id,
                date=self.order_id.date_order,
                company_id=self.company_id.id,
            )
            product_price += converted_extra_price
        
        # 3. Add the extra prices of any `no_variant` attributes
        return product_price + self.product_id._get_no_variant_attributes_price_extra(
            self.product_no_variant_attribute_value_ids
        )
