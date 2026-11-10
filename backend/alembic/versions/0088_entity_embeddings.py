"""Entity embedding rows on the platform metadata database.

Revision ID: 0088_entity_embeddings
Revises: 0087_model_service_shared_controls

pgvector is already installed by 0040_catalog_embeddings_vector. This table
does not reuse catalog_embeddings and does not add an ANN index.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0088_entity_embeddings"
down_revision: Union[str, None] = "0087_model_service_shared_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_embeddings (
            entity_id varchar(64) NOT NULL,
            head_version_id varchar(64) NOT NULL,
            content_hash varchar(64) NOT NULL,
            generation integer NOT NULL,
            processing_contract varchar(64) NOT NULL,
            embedding vector NOT NULL,
            embedding_dim integer NOT NULL,
            indexed_at timestamptz NOT NULL,
            CONSTRAINT pk_entity_embeddings PRIMARY KEY (entity_id),
            CONSTRAINT fk_entity_embeddings_entity_id
                FOREIGN KEY (entity_id)
                REFERENCES business_entities (id)
                ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE entity_embeddings")
