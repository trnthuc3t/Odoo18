/** @odoo-module **/
import { Component, useState, useSubEnv, onWillDestroy } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { formatCurrency } from "@web/core/currency";
import { _t } from '@web/core/l10n/translation';
import { rpc } from '@web/core/network/rpc';

export class DayTourConfiguratorDialog extends Component {
    static template = 'tour_combo_multiple_choice.DayTourConfiguratorDialog';
    static components = { Dialog };
    static props = {
        product_tmpl_id: Number,
        display_name: String,
        quantity: Number,
        currency_id: Number,
        company_id: { type: Number, optional: true },
        pricelist_id: { type: Number, optional: true },
        date: String,
        edit: { type: Boolean, optional: true },
        save: Function,
        discard: Function,
        close: Function,
    };

    setup() {
        this.state = useState({
            customerQuantity: this.props.quantity || 1,
            comboItems: [],
            totalPrice: 0,
            isLoading: false,
        });
        this._debounceTimer = null;
        useSubEnv({ currency: { id: this.props.currency_id } });
        onWillDestroy(() => {
            if (this._debounceTimer) clearTimeout(this._debounceTimer);
        });
        this._fetchComboItems();
    }

    onQuantityInput(ev) {
        const qty = parseInt(ev.target.value) || 1;
        this.state.customerQuantity = Math.max(1, qty);
        if (this._debounceTimer) clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(() => this._fetchComboItems(), 300);
    }

    async _fetchComboItems() {
        this.state.isLoading = true;
        try {
            const result = await rpc('/api/day_tour/get_combo_items', {
                product_template_id: this.props.product_tmpl_id,
                customer_quantity: this.state.customerQuantity,
                currency_id: this.props.currency_id,
            });
            const items = result.combos || [];
            const customerQty = this.state.customerQuantity;
            items.forEach(item => {
                item.formatted_fixed_price = formatCurrency(item.fixed_price || 0, this.props.currency_id);
                item.formatted_price_per_person = formatCurrency(item.price_per_person || 0, this.props.currency_id);
            });
            this.state.comboItems = items;
            // Total per person = sum of price_per_person for all items, then * customerQty
            const totalPerPerson = items.reduce(
                (sum, item) => sum + (item.price_per_person || 0), 0
            );
            this.state.totalPrice = totalPerPerson * customerQty;
        } finally {
            this.state.isLoading = false;
        }
    }

    get formattedTotalPrice() {
        return formatCurrency(this.state.totalPrice, this.props.currency_id);
    }

    get totalMessage() {
        return _t("Total: %s", this.formattedTotalPrice);
    }

    async confirm() {
        this.state.isLoading = true;
        try {
            const comboProductData = {
                quantity: this.state.customerQuantity,
            };
            const selectedItems = this.state.comboItems.map(item => ({
                combo_item_id: item.combo_item_id,
                product_id: item.product_id,
                no_variant_attribute_value_ids: [],
                product_custom_attribute_values: [],
            }));
            await this.props.save(comboProductData, selectedItems);
            this.props.close();
        } finally {
            this.state.isLoading = false;
        }
    }

    cancel() {
        if (!this.props.edit) {
            this.props.discard();
        }
        this.props.close();
    }
}
