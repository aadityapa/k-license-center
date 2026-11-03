-- V003__pkg_audit.sql
CREATE OR REPLACE PACKAGE pkg_audit AS
  PROCEDURE log_event (
    p_user_id      IN NUMBER,
    p_actor        IN VARCHAR2,
    p_action       IN VARCHAR2,
    p_entity_type  IN VARCHAR2,
    p_entity_id    IN NUMBER,
    p_request_id   IN VARCHAR2 DEFAULT NULL,
    p_ip_address   IN VARCHAR2 DEFAULT NULL,
    p_before_state IN CLOB     DEFAULT NULL,
    p_after_state  IN CLOB     DEFAULT NULL
  );
END pkg_audit;
/
CREATE OR REPLACE PACKAGE BODY pkg_audit AS
  PROCEDURE log_event (
    p_user_id      IN NUMBER,
    p_actor        IN VARCHAR2,
    p_action       IN VARCHAR2,
    p_entity_type  IN VARCHAR2,
    p_entity_id    IN NUMBER,
    p_request_id   IN VARCHAR2 DEFAULT NULL,
    p_ip_address   IN VARCHAR2 DEFAULT NULL,
    p_before_state IN CLOB     DEFAULT NULL,
    p_after_state  IN CLOB     DEFAULT NULL
  ) IS
  BEGIN
    INSERT INTO audit_logs
      (user_id, actor, action, entity_type, entity_id,
       request_id, ip_address, before_state, after_state)
    VALUES
      (p_user_id, NVL(p_actor,'SYSTEM'), p_action, p_entity_type, p_entity_id,
       p_request_id, p_ip_address, p_before_state, p_after_state);
  END log_event;
END pkg_audit;
/
