-- V901__scheduler.sql — daily expiry job
BEGIN
  DBMS_SCHEDULER.CREATE_JOB (
    job_name        => 'JOB_EXPIRE_LICENSES',
    job_type        => 'PLSQL_BLOCK',
    job_action      => 'BEGIN pkg_license.expire_due_licenses; COMMIT; END;',
    start_date      => SYSTIMESTAMP,
    repeat_interval => 'FREQ=DAILY; BYHOUR=0; BYMINUTE=15',
    enabled         => TRUE,
    comments        => 'Expire overdue licenses and emit expiry-warning events');
END;
/
