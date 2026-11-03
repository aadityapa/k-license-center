-- =====================================================================
-- 007_license_amount.sql
--
-- The amount charged for a licence, entered (compulsorily) when the licence
-- is created or a licence request is approved. It is what the dashboard
-- counts as revenue for that licence; renewals add their own amounts.
-- Existing licences keep amount NULL (the dashboard then falls back to the
-- plan price, if one is set).
-- =====================================================================
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS amount   NUMERIC(12,2);
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'INR' NOT NULL;
ALTER TABLE licenses ADD CONSTRAINT ck_license_amount CHECK (amount IS NULL OR amount >= 0);
