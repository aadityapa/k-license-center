-- ============================================================================
-- 008 — Reactivating an installation after a clock change
--
-- When the date/time of a computer is set back (typically: corrected after it
-- had been moved forward), the app blocks the licence and asks for
-- reactivation. Reactivation is decided by the licence server:
--   * APP   — the user pressed "Reactivate" in the app and the server confirmed
--             the computer's clock agrees with the server's time;
--   * ADMIN — an administrator reactivated the installation from the portal;
--             the app collects it the next time it contacts the server
--             (collected_at), even if its own check would not pass.
-- One row per reactivation; the portal shows the latest per installation.
-- ============================================================================

CREATE TABLE IF NOT EXISTS clock_reactivations (
  reactivation_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id       BIGINT       NOT NULL REFERENCES products(product_id),
  installation_id  VARCHAR(100) NOT NULL,
  source           VARCHAR(10)  NOT NULL,
  requested_by     BIGINT       REFERENCES users(user_id),
  requested_at     TIMESTAMPTZ  DEFAULT now() NOT NULL,
  collected_at     TIMESTAMPTZ,
  local_time       VARCHAR(40),
  note             VARCHAR(500),
  CONSTRAINT ck_clockre_source CHECK (source IN ('APP', 'ADMIN'))
);

CREATE INDEX IF NOT EXISTS ix_clockre_install ON clock_reactivations (installation_id, requested_at DESC);
