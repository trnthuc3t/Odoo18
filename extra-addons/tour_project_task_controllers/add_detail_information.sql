-- Add detail_information column to product_template table
ALTER TABLE account_move ADD COLUMN tasks_generated BOOLEAN DEFAULT FALSE;
ALTER TABLE account_move ADD COLUMN is_guarantee_invoice BOOLEAN DEFAULT FALSE;
ALTER TABLE project_task ADD COLUMN mentor_id INTEGER;
ALTER TABLE project_task ADD COLUMN manager_id INTEGER;
ALTER TABLE project_task ADD COLUMN depend_on_ids INTEGER[];
ALTER TABLE project_task ADD COLUMN blocking_task_ids INTEGER[];
ALTER TABLE project_task ADD COLUMN has_dependencies BOOLEAN DEFAULT FALSE;
ALTER TABLE project_task ADD COLUMN dependencies_completed BOOLEAN DEFAULT FALSE;
ALTER TABLE project_task ADD COLUMN can_start BOOLEAN DEFAULT TRUE;