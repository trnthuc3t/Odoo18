-- Add detail_information column to product_template table
ALTER TABLE crm_lead ADD COLUMN crm_lead_line_ids INTEGER[];
ALTER TABLE crm_lead ADD COLUMN detail_information TEXT;
ALTER TABLE crm_lead ADD COLUMN currency_id INTEGER;
ALTER TABLE crm_lead ADD COLUMN is_done_order BOOLEAN DEFAULT FALSE;
ALTER TABLE crm_lead ADD COLUMN crm_product_ids INTEGER[];