-- Run once against your dedicated Neon database using the operator setup command.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS aegis;
REVOKE ALL ON SCHEMA aegis FROM PUBLIC;

CREATE TABLE IF NOT EXISTS aegis.documents (
    workspace_id text NOT NULL,
    document_id text NOT NULL,
    batch jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, document_id),
    CHECK (batch->>'workspace_id' = workspace_id),
    CHECK (batch->'document'->>'id' = document_id)
);
CREATE TABLE IF NOT EXISTS aegis.vectors (
    workspace_id text NOT NULL,
    document_id text NOT NULL,
    chunk_id text NOT NULL,
    embedding public.vector(768) NOT NULL,
    PRIMARY KEY (workspace_id, chunk_id),
    FOREIGN KEY (workspace_id, document_id)
        REFERENCES aegis.documents(workspace_id, document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS aegis_vectors_document ON aegis.vectors(workspace_id, document_id);

CREATE TABLE IF NOT EXISTS aegis.users (
    user_id text PRIMARY KEY,
    platform_admin boolean NOT NULL DEFAULT false,
    disabled boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS aegis.memberships (
    user_id text NOT NULL REFERENCES aegis.users(user_id) ON DELETE CASCADE,
    workspace_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('viewer', 'editor', 'admin')),
    PRIMARY KEY(user_id, workspace_id)
);
REVOKE ALL ON ALL TABLES IN SCHEMA aegis FROM PUBLIC;
