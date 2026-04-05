/** @odoo-module **/
import { Component, useState, useSubEnv } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { ProductCard } from '@sale/js/product_card/product_card';
import { QuantityButtons } from '@sale/js/quantity_buttons/quantity_buttons';
import { formatCurrency } from "@web/core/currency";
import { _t } from '@web/core/l10n/translation';
import { rpc } from '@web/core/network/rpc';
import { serializeDateTime } from "@web/core/l10n/dates";
import { uuid } from "@web/views/utils";
// Patch/inherit SaleOrderLineProductField to add _openComboMultipleConfigurator and update _onProductTemplateUpdate
import { registry } from '@web/core/registry';
import { SaleOrderLineProductField } from '@sale/js/sale_product_field';
import { ProductCombo } from '@sale/js/models/product_combo';
import { ProductComboItem } from '@sale/js/models/product_combo_item';
import { getLinkedSaleOrderLines, serializeComboItem } from '@sale/js/sale_utils';
import { ProductConfiguratorDialog } from '@sale/js/product_configurator_dialog/product_configurator_dialog';
import { ProductTemplateAttributeLine } from '@sale/js/models/product_template_attribute_line';
import { useService } from '@web/core/utils/hooks'
import { DayTourConfiguratorDialog } from '@tour_combo_multiple_choice/js/day_tour_configurator';

// Extended ProductComboItem to support fixed_price/lst_price for combo multiple choice
class ProductComboItemMultiple extends ProductComboItem {
	constructor({id, extra_price, is_selected, is_configurable, product, lst_price, use_lst_price, fixed_price, use_fixed_price, quantity}) {
		super({id, extra_price, is_selected, is_configurable, product});
		this.lst_price = lst_price;
		this.use_lst_price = use_lst_price;
		this.fixed_price = fixed_price;
		this.use_fixed_price = use_fixed_price;
		this.quantity = quantity || 1.0;
	}

	deepCopy() {
		const copy = new ProductComboItemMultiple(JSON.parse(JSON.stringify(this)));
		return copy;
	}
}

// Extended ProductCombo to use ProductComboItemMultiple
class ProductComboMultiple extends ProductCombo {
	constructor({id, name, combo_items}) {
		super({id, name, combo_items: []});
		this.combo_items = combo_items.map(item => new ProductComboItemMultiple(item));
	}
}

// ComboMultipleChoiceConfiguratorDialog: similar to ComboConfiguratorDialog but allows multiple selection per section
export class ComboMultipleChoiceConfiguratorDialog extends Component {
	static template = 'tour_combo_multiple_choice.ComboMultipleChoiceConfiguratorDialog';
	static components = { Dialog, ProductCard, QuantityButtons };
	static props = {
		product_tmpl_id: Number,
		display_name: String,
		quantity: Number,
		price: Number,
		combos: { type: Array },
		currency_id: Number,
		company_id: { type: Number, optional: true },
		pricelist_id: { type: Number, optional: true },
		date: String,
		price_info: { type: String, optional: true },
		edit: { type: Boolean, optional: true },
		options: {
			type: Object,
			optional: true,
			shape: {
				showQuantity : { type: Boolean, optional: true },
			},
		},
		save: Function,
		discard: Function,
		close: Function,
	};
	static defaultProps = {
		options: {
			showQuantity: true,
		},
	};

	setup() {
		this.dialog = useService('dialog');
		this.state = useState({
			// Map combo id to Set of selected combo item ids
			selectedComboItems: new Map(),
			// Map comboItem.id to configured ProductComboItem (for configurable items)
			configuredComboItems: new Map(),
			quantity: this.props.quantity,
			basePrice: this.props.price,
			isLoading: false,
		});
		this.getPriceUrl = '/sale/combo_configurator/get_price';
		useSubEnv({ currency: { id: this.props.currency_id } });
		this._initSelectedComboItems();
	}

	_initSelectedComboItems() {
		// Initialize with all preselected items (if any)
		for (const combo of this.props.combos) {
			const selected = combo.selectedComboItem ? [combo.selectedComboItem] : [];
			// For multiple choice, we need to check all items that are selected
			const selectedItems = combo.combo_items.filter(item => item.is_selected);
			this.state.selectedComboItems.set(combo.id, new Set(selectedItems.map(item => item.id)));
		}
	}

	async toggleComboItem(comboId, comboItem) {
		// Toggle selection for a combo item (multi-select)
		const set = this.state.selectedComboItems.get(comboId) || new Set();
		
		if (set.has(comboItem.id)) {
			// Deselect: remove from selection and configured items
			set.delete(comboItem.id);
			this.state.selectedComboItems.set(comboId, new Set(set));
			this.state.configuredComboItems.delete(comboItem.id);
		} else {
			// Select: check if configurable
			if (comboItem.is_configurable) {
				// Get the configured version if it exists, otherwise use the original
				const itemToConfigure = this.state.configuredComboItems.get(comboItem.id) || comboItem;
				const product = itemToConfigure.product;
				
				// Open product configurator
				this.dialog.add(ProductConfiguratorDialog, {
					productTemplateId: product.product_tmpl_id,
					ptavIds: product.selectedPtavIds,
					customPtavs: product.selectedCustomPtavs,
					quantity: 1,
					companyId: this.props.company_id,
					pricelistId: this.props.pricelist_id,
					currencyId: this.props.currency_id,
					soDate: this.props.date,
					edit: true, // Hide the optional products, if any.
					options: { canChangeVariant: false, showQuantity: false, showPrice: false },
					save: async configuredProduct => {
						// Save configured item
						const configuredComboItem = comboItem.deepCopy();
						configuredComboItem.product.ptals = configuredProduct.attribute_lines.map(
							ProductTemplateAttributeLine.fromProductConfiguratorPtal
						);
						this.state.configuredComboItems.set(comboItem.id, configuredComboItem);
						// Add to selection
						set.add(comboItem.id);
						this.state.selectedComboItems.set(comboId, new Set(set));
					},
					discard: () => {
						// Don't add to selection if discarded
					},
					...this._getAdditionalDialogProps(),
				});
			} else {
				// Non-configurable: just add to selection
				set.add(comboItem.id);
				this.state.selectedComboItems.set(comboId, new Set(set));
			}
		}
	}

	async selectAllInCombo(comboId, comboItems) {
		// Select all items in a combo section, opening configurators sequentially if needed
		const configurableItems = comboItems.filter(item => item.is_configurable);
		const nonConfigurableItems = comboItems.filter(item => !item.is_configurable);
		
		// First, add all non-configurable items
		const set = this.state.selectedComboItems.get(comboId) || new Set();
		for (const item of nonConfigurableItems) {
			set.add(item.id);
		}
		this.state.selectedComboItems.set(comboId, new Set(set));
		
		// Then, configure configurable items sequentially
		for (const item of configurableItems) {
			// Skip if already selected
			if (set.has(item.id)) continue;
			
			await new Promise((resolve) => {
				const itemToConfigure = this.state.configuredComboItems.get(item.id) || item;
				const product = itemToConfigure.product;
				
				this.dialog.add(ProductConfiguratorDialog, {
					productTemplateId: product.product_tmpl_id,
					ptavIds: product.selectedPtavIds,
					customPtavs: product.selectedCustomPtavs,
					quantity: 1,
					companyId: this.props.company_id,
					pricelistId: this.props.pricelist_id,
					currencyId: this.props.currency_id,
					soDate: this.props.date,
					edit: true,
					options: { canChangeVariant: false, showQuantity: false, showPrice: false },
					save: async configuredProduct => {
						const configuredComboItem = item.deepCopy();
						configuredComboItem.product.ptals = configuredProduct.attribute_lines.map(
							ProductTemplateAttributeLine.fromProductConfiguratorPtal
						);
						this.state.configuredComboItems.set(item.id, configuredComboItem);
						set.add(item.id);
						this.state.selectedComboItems.set(comboId, new Set(set));
						resolve();
					},
					discard: () => {
						// Skip this item if discarded
						resolve();
					},
					close: () => resolve(),
					...this._getAdditionalDialogProps(),
				});
			});
		}
	}

	async selectAllCombos() {
		// Select all items in all combos, opening configurators sequentially
		for (const combo of this.props.combos) {
			await this.selectAllInCombo(combo.id, combo.combo_items);
		}
	}
	deselectAllInCombo(comboId, comboItems) {
		// Deselect all items in a combo section
		this.state.selectedComboItems.set(comboId, new Set());
	}

	deselectAllCombos() {
		// Deselect all items in all combos
		for (const combo of this.props.combos) {
			this.deselectAllInCombo(combo.id, combo.combo_items);
		}
	}
	async setQuantity(quantity) {
		if (quantity <= 0) quantity = 1;
		this.state.quantity = quantity;
		this.state.basePrice = await rpc(this.getPriceUrl, {
			product_tmpl_id: this.props.product_tmpl_id,
			currency_id: this.props.currency_id,
			quantity: quantity,
			date: this.props.date,
			company_id: this.props.company_id,
			pricelist_id: this.props.pricelist_id,
		});
	}

	get totalMessage() {
		return _t("Total: %s", this.formattedTotalPrice);
	}

	get formattedTotalPrice() {
		return formatCurrency(this.state.quantity * this._comboPrice, this.props.currency_id);
	}

	get areAllCombosSelected() {
		// At least one item selected in each combo
		return this.props.combos.every(combo => (this.state.selectedComboItems.get(combo.id)?.size || 0) > 0);
	}

	get _comboPrice() {
		// For combo multiple choice, sum fixed_price/lst_price of all selected items
		let totalPrice = 0;
		for (const combo of this.props.combos) {
			const set = this.state.selectedComboItems.get(combo.id) || new Set();
			for (const item of combo.combo_items) {
				if (set.has(item.id)) {
					// Use configured version if available for accurate pricing
					const finalItem = this.state.configuredComboItems.get(item.id) || item;
					
					// Priority: fixed_price > lst_price > extra_price
					if (finalItem.use_fixed_price && finalItem.fixed_price !== undefined) {
						// Use fixed_price for multiple choice combo
						totalPrice += finalItem.fixed_price + (finalItem.product?.selectedNoVariantPtavsPriceExtra || 0);
					} else if (finalItem.use_lst_price && finalItem.lst_price !== undefined) {
						// Fallback to lst_price + extra_price
						totalPrice += finalItem.lst_price + (finalItem.product?.selectedNoVariantPtavsPriceExtra || 0);
					} else {
						// Fallback to extra_price (for regular combo)
						totalPrice += finalItem.totalExtraPrice || 0;
					}
				}
			}
		}
		// If using fixed_price or lst_price, don't add base price; otherwise use original logic
		const hasDirectPriceItems = this.props.combos.some(combo => 
			combo.combo_items.some(item => item.use_fixed_price || item.use_lst_price)
		);
		return hasDirectPriceItems ? totalPrice : (this.state.basePrice + totalPrice);
	}

	get _comboProductData() {
		return { 'quantity': this.state.quantity };
	}

	get _selectedComboItems() {
		// Return all selected combo items, using configured versions if available
		const result = [];
		for (const combo of this.props.combos) {
			const set = this.state.selectedComboItems.get(combo.id) || new Set();
			for (const item of combo.combo_items) {
				if (set.has(item.id)) {
					// Use configured version if available, otherwise use original
					const finalItem = this.state.configuredComboItems.get(item.id) || item;
					result.push(finalItem);
				}
			}
		}
		return result;
	}

	async confirm(options) {
		this.state.isLoading = true;
		await this.props.save(this._comboProductData, this._selectedComboItems, options).finally(
			() => this.state.isLoading = false
		);
		this.props.close();
	}

	cancel() {
		if (!this.props.edit) {
			this.props.discard();
		}
		this.props.close();
	}

	/**
	 * Hook to append additional props in overriding modules.
	 *
	 * @return {Object} The additional props.
	 */
	_getAdditionalDialogProps() {
		return {};
	}
}

const patchSaleOrderLineProductField = (Base) => class extends Base {
	async _onProductTemplateUpdate() {
		const result = await this.orm.call(
			'product.template',
			'get_single_product_variant',
			[this.props.record.data.product_template_id[0]],
			{
				context: this.context,
			}
		);
		if (result && result.is_day_tour) {
			// Update product_id and open day tour configurator
			await this.props.record.update({
				product_id: [result.product_id, result.product_name],
			});
			await this._openDayTourConfigurator();
		} else if (result && result.is_combo_multiple_choice) {
			// Update product_id and open multiple choice configurator
			await this.props.record.update({
				product_id: [result.product_id, result.product_name],
			});
			await this._openComboMultipleConfigurator();
		} else if (result && result.is_combo) {
			await this.props.record.update({
				product_id: [result.product_id, result.product_name],
			});
			await this._openComboConfigurator();
		} else if(result && result.product_id) {
            if (this.props.record.data.product_id != result.product_id.id) {
                if (result.is_combo) {
                    await this.props.record.update({
                        product_id: [result.product_id, result.product_name],
                    });
                    this._openComboConfigurator();
                } else if (result.has_optional_products) {
                    this._openProductConfigurator();
                } else {
                    await this.props.record.update({
                        product_id: [result.product_id, result.product_name],
                    });
                    this._onProductUpdate();
                }
            }
        } else {
            if (result && result.sale_warning) {
                const {type, title, message} = result.sale_warning
                if (type === 'block') {
                    // display warning block, and remove blocking product
                    this.dialog.add(WarningDialog, { title, message });
                    this.props.record.update({'product_template_id': false})
                    return
                } else if (type == 'warning') {
                    // show the warning but proceed with the configurator opening
                    this.notification.add(message, {
                        title,
                        type: "warning",
                    });
                }
            }
            if (!result.mode || result.mode === 'configurator') {
                this._openProductConfigurator();
            } else {
                // only triggered when sale_product_matrix is installed.
                this._openGridConfigurator();
            }
        }
	}

	async isComboMultipleChoice() {
		const result = await rpc('/api/is_combo_multiple_choice', {
			product_template_id: this.props.record.data.product_template_id[0],
		});
		return !!result;
	}

	async isDayTour() {
		const result = await rpc('/api/is_day_tour', {
			product_template_id: this.props.record.data.product_template_id[0],
		});
		return !!result;
	}

	async onEditConfiguration() {
        if (this.isConfigurableLine) {
            this._editLineConfiguration();
        } else if (this.isCombo) {
			if (await this.isDayTour()) {
				this._openDayTourConfigurator(true);
			} else if (await this.isComboMultipleChoice()) {
				this._openComboMultipleConfigurator(true);
			} else {
            	this._openComboConfigurator(true);
			}
        } else if (this.isConfigurableTemplate) {
            this._openProductConfigurator(true);
        }
    }

	async _openDayTourConfigurator(edit=false) {
		const saleOrder = this.props.record.model.root.data;
		const comboLineRecord = this.props.record;

		const dialogProps = {
			product_tmpl_id: comboLineRecord.data.product_template_id[0],
			display_name: comboLineRecord.data.product_template_id[1],
			quantity: comboLineRecord.data.product_uom_qty || 1,
			currency_id: comboLineRecord.data.currency_id[0],
			company_id: saleOrder.company_id[0],
			pricelist_id: saleOrder.pricelist_id[0],
			date: serializeDateTime(saleOrder.date_order),
			edit: edit,
			save: async (comboProductData, selectedItems) => {
				saleOrder.order_line.leaveEditMode();
				const comboLineValues = {
					product_uom_qty: comboProductData.quantity,
					selected_combo_items: JSON.stringify(selectedItems),
				};
				if (!edit) {
					comboLineValues.virtual_id = uuid();
				}
				await comboLineRecord.update(comboLineValues);
				await saleOrder.order_line._sort();
			},
			discard: () => saleOrder.order_line.delete(comboLineRecord),
			close: () => {},
		};
		this.dialog.add(DayTourConfiguratorDialog, dialogProps);
	}

	async _openComboMultipleConfigurator(edit=false) {
		const saleOrder = this.props.record.model.root.data;
		const comboLineRecord = this.props.record;
		const saleOrderLine = this.props.record.data;
		
		// Get linked combo item lines for edit mode (filter out section lines)
		const comboItemLineRecords = getLinkedSaleOrderLines(comboLineRecord).filter(
			record => record.data.display_type !== 'line_section' && record.data.combo_item_id
		);
		
		const selectedComboItems = await Promise.all(comboItemLineRecords.map(async record => ({
			id: record.data.combo_item_id[0],
			no_variant_ptav_ids: edit ? this._getNoVariantPtavIds(record.data) : [],
			custom_ptavs: edit ? await this._getCustomPtavs(record.data) : [],
		})));
		// Call RPC to get combo data
		const rpcParams = {
			product_tmpl_id: comboLineRecord.data.product_template_id[0],
			currency_id: comboLineRecord.data.currency_id[0],
			quantity: comboLineRecord.data.product_uom_qty,
			date: serializeDateTime(saleOrder.date_order),
			company_id: saleOrder.company_id[0],
			pricelist_id: saleOrder.pricelist_id[0],
			selected_combo_items: selectedComboItems,
			...this._getAdditionalRpcParams(),
		};
		
		const rpcResult = await rpc('/sale/combo_configurator/get_data', rpcParams);
		const { combos, ...remainingData } = rpcResult;
		// Map combos to ProductComboMultiple instances (supports lst_price)
		const productCombos = combos.map(combo => new ProductComboMultiple(combo));
		const dialogProps = {
			combos: productCombos,
			...remainingData,
			company_id: saleOrder.company_id[0],
			pricelist_id: saleOrder.pricelist_id[0],
			date: serializeDateTime(saleOrder.date_order),
			edit: edit,
			save: async (comboProductData, selectedComboItems) => {
				saleOrder.order_line.leaveEditMode();
				const comboLineValues = {
					product_uom_qty: comboProductData.quantity,
					selected_combo_items: JSON.stringify(
						selectedComboItems.map(serializeComboItem)
					),
				};
				if (!edit) {
					comboLineValues.virtual_id = uuid();
				}
				await comboLineRecord.update(comboLineValues);
				await saleOrder.order_line._sort();
			},
			discard: () => saleOrder.order_line.delete(comboLineRecord),
			close: () => {},
		};
		this.dialog.add(ComboMultipleChoiceConfiguratorDialog, dialogProps);
	}
};

const solProductMany2one = registry.category("fields").get("sol_product_many2one");
if (solProductMany2one) {
	solProductMany2one.component = patchSaleOrderLineProductField(SaleOrderLineProductField);
}
