-- V002__indexes.sql — secondary indexes (PK/UNIQUE indexes already exist)

CREATE INDEX ix_plans_product        ON product_plans (product_id);
CREATE INDEX ix_customers_name_u     ON customers (UPPER(company_name));
CREATE INDEX ix_customers_email_u    ON customers (UPPER(email));
CREATE INDEX ix_customers_mobile     ON customers (mobile);

CREATE INDEX ix_licenses_customer    ON licenses (customer_id);
CREATE INDEX ix_licenses_product     ON licenses (product_id);
CREATE INDEX ix_licenses_plan        ON licenses (plan_id);
CREATE INDEX ix_licenses_status      ON licenses (status);
CREATE INDEX ix_licenses_expiry      ON licenses (expiry_date);

CREATE INDEX ix_keys_license         ON license_keys (license_id);
CREATE INDEX ix_keys_hash            ON license_keys (key_hash);

CREATE INDEX ix_act_license          ON license_activations (license_id);
CREATE INDEX ix_act_install          ON license_activations (installation_id);
CREATE INDEX ix_act_status           ON license_activations (status);

CREATE INDEX ix_renewals_license     ON license_renewals (license_id);
CREATE INDEX ix_history_license      ON license_history (license_id);

CREATE INDEX ix_apilog_created       ON api_request_logs (created_at);
CREATE INDEX ix_apilog_client        ON api_request_logs (client_id);

CREATE INDEX ix_audit_entity         ON audit_logs (entity_type, entity_id);
CREATE INDEX ix_audit_created        ON audit_logs (created_at);
CREATE INDEX ix_audit_action         ON audit_logs (action);

CREATE INDEX ix_notif_status         ON notification_events (status, created_at);
