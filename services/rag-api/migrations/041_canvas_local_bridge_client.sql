-- Dedicated credential for the portable local Canvas bridge.
--
-- The browser-created one-time code remains single-use. A successful portable-client claim rotates
-- to a separate random bridge credential; only its SHA-256 digest is persisted. Canvas PATs are
-- neither accepted by this protocol nor represented by any column.

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (41, '041_canvas_local_bridge_client.sql');
