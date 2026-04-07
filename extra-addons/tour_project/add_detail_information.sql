-- Add detail_information column to product_template table
ALTER TABLE project_project ADD COLUMN order_id INTEGER;
ALTER TABLE project_project ADD COLUMN sale_tag_ids INTEGER[];