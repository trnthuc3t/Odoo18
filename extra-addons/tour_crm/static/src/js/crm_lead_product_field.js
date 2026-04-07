/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";

/**
 * Widget for product selection in CRM Lead Lines.
 * Simplified version of sol_product_many2one with product configurator.
 */
export class CrmLeadProductField extends Many2OneField {
    
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        
        let isMounted = false;
        let previousValue = this.props.record.data[this.props.name];
        
        // Watch for changes in the field value
        useEffect(
            (value) => {
                // Skip if it's the first mount (loading existing records)
                if (!isMounted) {
                    isMounted = true;
                    previousValue = value;
                    return;
                }
                
                // Only proceed if value actually changed
                const currentId = Array.isArray(value) ? value[0] : value;
                const previousId = Array.isArray(previousValue) ? previousValue[0] : previousValue;
                
                if (this.props.name === 'product_template_id' && currentId && currentId !== previousId) {
                    previousValue = value;
                    this._onProductTemplateUpdate(currentId);
                } else {
                    previousValue = value;
                }
            },
            () => [this.props.record.data[this.props.name]]
        );
    }

    get hasExternalButton() {
        // Keep external button, even if field is specified as 'no_open'
        const res = super.hasExternalButton;
        return res || (!!this.props.record.data[this.props.name] && !this.state.isFloating);
    }

    async _onProductTemplateUpdate(productTemplateId) {
        try {
            // Get product template info
            const productTemplate = await this.orm.call(
                'product.template',
                'get_single_product_variant',
                [productTemplateId],
                {
                    context: {
                        ...this.props.record.context,
                    }
                }
            );
            
            if (productTemplate && productTemplate.product_id) {
                // Has a single variant, auto-select it and get tax info from template
                const templateData = await this.orm.read(
                    'product.template',
                    [productTemplateId],
                    ['taxes_id']
                );
                
                const updateData = {
                    product_id: [productTemplate.product_id, productTemplate.product_name],
                };
                
                // Set tax if template has taxes - read tax name to avoid "Unnamed" error
                if (templateData[0].taxes_id && templateData[0].taxes_id.length > 0) {
                    const taxData = await this.orm.read(
                        'account.tax',
                        [templateData[0].taxes_id[0]],
                        ['display_name']
                    );
                    updateData.tax_id = [taxData[0].id, taxData[0].display_name];
                }
                
                // Price will be set by Python onchange
                await this.props.record.update(updateData);
            } else {
                // Multiple variants, open configurator
                this._openProductConfigurator(productTemplateId);
            }
        } catch (error) {
            console.error('[CRM Lead Product] Error loading product:', error);
            this.notification.add(
                _t("Failed to load product information. Please try again."),
                { type: "danger" }
            );
        }
    }

    async _openProductConfigurator(productTemplateId) {
        try {
            const today = new Date().toISOString().split('T')[0];
            
            // Get first pricelist from product
            const productData = await this.orm.read(
                'product.product',
                [this.props.record.data.product_id?.[0]],
                ['product_tmpl_id']
            );
            
            // Search for pricelist items related to this product
            const pricelistItems = await this.orm.searchRead(
                'product.pricelist.item',
                [['product_tmpl_id', '=', productTemplateId]],
                ['pricelist_id'],
                { limit: 1 }
            );
            
            const pricelistId = pricelistItems.length > 0 ? pricelistItems[0].pricelist_id[0] : 0;
            
            this.dialog.add(ProductConfiguratorDialog, {
                productTemplateId: productTemplateId,
                ptavIds: [],
                customPtavs: [],
                quantity: this.props.record.data.quantity || 1,
                companyId: this.props.record.data.crm_lead_id?.data?.company_id?.[0] || this.env.services.company.currentCompany.id,
                pricelistId: pricelistId,
                currencyId: this.props.record.data.currency_id?.[0],
                soDate: today,
                edit: false,
                save: async (product) => {
                    // Get tax info from product template
                    const templateData = await this.orm.read(
                        'product.template',
                        [productTemplateId],
                        ['taxes_id']
                    );
                    
                    // Only update product_id and tax - price will be set by Python onchange
                    const updateData = {
                        product_id: [product.id, product.display_name],
                    };
                    
                    // Set tax if template has taxes - read tax name to avoid "Unnamed" error
                    if (templateData[0].taxes_id && templateData[0].taxes_id.length > 0) {
                        const taxData = await this.orm.read(
                            'account.tax',
                            [templateData[0].taxes_id[0]],
                            ['display_name']
                        );
                        updateData.tax_id = [taxData[0].id, taxData[0].display_name];
                    }
                    
                    // Price and quantity will be handled by Python onchange
                    await this.props.record.update(updateData);
                },
                discard: () => {},
                close: () => {},
            });
        } catch (error) {
            console.error('[CRM Lead Product] Error opening configurator:', error);
            this.notification.add(
                _t("Failed to open product configurator. Please try again."),
                { type: "danger" }
            );
        }
    }
}

export const crmLeadProductField = {
    ...many2OneField,
    component: CrmLeadProductField,
};

registry.category("fields").add("crm_lead_product_many2one", crmLeadProductField);
