"""initial schema

Revision ID: 0001
Revises: 
"""

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


AUDIT_TRIGGER = """
CREATE FUNCTION reject_audit_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_append_only
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION reject_audit_change();
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('runbooks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_runbooks')),
    sa.UniqueConstraint('key', name=op.f('uq_runbooks_key'))
    )
    op.create_table('sla_policies',
    sa.Column('priority', sa.Enum('P1', 'P2', 'P3', 'P4', name='priority', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('response_minutes', sa.Integer(), nullable=False),
    sa.Column('resolution_minutes', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('priority', name=op.f('pk_sla_policies'))
    )
    op.create_table('teams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_teams')),
    sa.UniqueConstraint('name', name=op.f('uq_teams_name'))
    )
    op.create_table('knowledge_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_type', sa.Enum('kb_article', 'resolved_incident', name='documentsource', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source_ref', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=True),
    sa.Column('access_level', sa.Enum('public', 'internal', 'restricted', name='accesslevel', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_knowledge_documents_team_id_teams')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_documents')),
    sa.UniqueConstraint('source_type', 'source_ref', name=op.f('uq_knowledge_documents_source_type_source_ref'))
    )
    op.create_index(op.f('ix_knowledge_documents_category'), 'knowledge_documents', ['category'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('requester', 'agent', 'manager', 'admin', name='role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_users_team_id_teams')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_team_id'), 'users', ['team_id'], unique=False)
    op.create_table('incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('impact', sa.Enum('high', 'medium', 'low', name='impact', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('urgency', sa.Enum('high', 'medium', 'low', name='urgency', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority', sa.Enum('P1', 'P2', 'P3', 'P4', name='priority', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('new', 'assigned', 'in_progress', 'on_hold', 'resolved', 'closed', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('channel', sa.Enum('portal', 'email', 'phone', 'monitoring', name='channel', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('category', sa.Enum('network', 'access_identity', 'hardware', 'software_application', 'database', 'cloud_infrastructure', 'security', 'email_collaboration', name='category', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('category_confidence', sa.Float(), nullable=True),
    sa.Column('category_corrected', sa.Boolean(), nullable=False),
    sa.Column('requester_id', sa.Integer(), nullable=False),
    sa.Column('assignee_id', sa.Integer(), nullable=True),
    sa.Column('team_id', sa.Integer(), nullable=True),
    sa.Column('response_due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolution_due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_response_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('on_hold_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sla_breached', sa.Boolean(), nullable=False),
    sa.Column('sla_breached_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('escalation_level', sa.Integer(), nullable=False),
    sa.Column('resolution_notes', sa.Text(), nullable=True),
    sa.Column('sla_risk_score', sa.Float(), nullable=True),
    sa.Column('sla_risk_scored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sla_risk_alerted', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], name=op.f('fk_incidents_assignee_id_users')),
    sa.ForeignKeyConstraint(['requester_id'], ['users.id'], name=op.f('fk_incidents_requester_id_users')),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_incidents_team_id_teams')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incidents'))
    )
    op.create_index(op.f('ix_incidents_assignee_id'), 'incidents', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_incidents_category'), 'incidents', ['category'], unique=False)
    op.create_index('ix_incidents_created_at', 'incidents', ['created_at'], unique=False)
    op.create_index(op.f('ix_incidents_priority'), 'incidents', ['priority'], unique=False)
    op.create_index(op.f('ix_incidents_requester_id'), 'incidents', ['requester_id'], unique=False)
    op.create_index(op.f('ix_incidents_sla_breached'), 'incidents', ['sla_breached'], unique=False)
    op.create_index(op.f('ix_incidents_status'), 'incidents', ['status'], unique=False)
    op.create_index('ix_incidents_status_due', 'incidents', ['status', 'resolution_due_at'], unique=False)
    op.create_index('ix_incidents_team_status', 'incidents', ['team_id', 'status'], unique=False)
    op.create_table('knowledge_chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
    sa.Column('flagged_injection', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_knowledge_chunks_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name=op.f('uq_knowledge_chunks_document_id_chunk_index'))
    )
    op.create_index(op.f('ix_knowledge_chunks_document_id'), 'knowledge_chunks', ['document_id'], unique=False)
    op.create_index('ix_knowledge_chunks_embedding', 'knowledge_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('family_id', sa.String(length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('ai_conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_ai_conversations_incident_id_incidents')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_conversations_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_conversations'))
    )
    op.create_index(op.f('ix_ai_conversations_user_id'), 'ai_conversations', ['user_id'], unique=False)
    op.create_table('ai_recommendations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('insufficient_evidence', sa.Boolean(), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('helpful', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_ai_recommendations_incident_id_incidents')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_recommendations_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_recommendations'))
    )
    op.create_index(op.f('ix_ai_recommendations_incident_id'), 'ai_recommendations', ['incident_id'], unique=False)
    op.create_index(op.f('ix_ai_recommendations_user_id'), 'ai_recommendations', ['user_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users')),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_audit_logs_incident_id_incidents')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_incident_id'), 'audit_logs', ['incident_id'], unique=False)
    op.create_table('incident_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_internal', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_incident_comments_author_id_users')),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_incident_comments_incident_id_incidents')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident_comments'))
    )
    op.create_index(op.f('ix_incident_comments_incident_id'), 'incident_comments', ['incident_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.Enum('assigned', 'status_changed', 'comment', 'sla_risk', 'sla_breach', 'escalated', 'approval_required', 'remediation_result', name='notificationtype', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('dedupe_key', sa.String(length=100), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_notifications_incident_id_incidents')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'read_at'], unique=False)
    op.create_index('uq_notifications_dedupe', 'notifications', ['user_id', 'dedupe_key'], unique=True, postgresql_where=sa.text('dedupe_key IS NOT NULL'))
    op.create_table('predictions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('category', 'sla_risk', 'routing', name='predictionkind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('model_version', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=100), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('accepted', sa.Boolean(), nullable=True),
    sa.Column('corrected_value', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_predictions_incident_id_incidents')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_predictions'))
    )
    op.create_index(op.f('ix_predictions_incident_id'), 'predictions', ['incident_id'], unique=False)
    op.create_index(op.f('ix_predictions_kind'), 'predictions', ['kind'], unique=False)
    op.create_table('remediation_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('runbook_id', sa.Integer(), nullable=False),
    sa.Column('requested_by_id', sa.Integer(), nullable=False),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('pending_approval', 'approved', 'rejected', 'running', 'succeeded', 'failed', name='remediationstatus', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('target', sa.String(length=200), nullable=False),
    sa.Column('justification', sa.Text(), nullable=False),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], name=op.f('fk_remediation_requests_decided_by_id_users')),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_remediation_requests_incident_id_incidents')),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name=op.f('fk_remediation_requests_requested_by_id_users')),
    sa.ForeignKeyConstraint(['runbook_id'], ['runbooks.id'], name=op.f('fk_remediation_requests_runbook_id_runbooks')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_remediation_requests'))
    )
    op.create_index(op.f('ix_remediation_requests_incident_id'), 'remediation_requests', ['incident_id'], unique=False)
    op.create_index(op.f('ix_remediation_requests_status'), 'remediation_requests', ['status'], unique=False)
    op.create_table('ai_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('recommendation_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id'], name=op.f('fk_ai_messages_conversation_id_ai_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recommendation_id'], ['ai_recommendations.id'], name=op.f('fk_ai_messages_recommendation_id_ai_recommendations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_messages'))
    )
    op.create_index(op.f('ix_ai_messages_conversation_id'), 'ai_messages', ['conversation_id'], unique=False)

    op.execute(AUDIT_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION reject_audit_change")
    op.drop_index(op.f('ix_ai_messages_conversation_id'), table_name='ai_messages')
    op.drop_table('ai_messages')
    op.drop_index(op.f('ix_remediation_requests_status'), table_name='remediation_requests')
    op.drop_index(op.f('ix_remediation_requests_incident_id'), table_name='remediation_requests')
    op.drop_table('remediation_requests')
    op.drop_index(op.f('ix_predictions_kind'), table_name='predictions')
    op.drop_index(op.f('ix_predictions_incident_id'), table_name='predictions')
    op.drop_table('predictions')
    op.drop_index('uq_notifications_dedupe', table_name='notifications', postgresql_where=sa.text('dedupe_key IS NOT NULL'))
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_incident_comments_incident_id'), table_name='incident_comments')
    op.drop_table('incident_comments')
    op.drop_index(op.f('ix_audit_logs_incident_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_ai_recommendations_user_id'), table_name='ai_recommendations')
    op.drop_index(op.f('ix_ai_recommendations_incident_id'), table_name='ai_recommendations')
    op.drop_table('ai_recommendations')
    op.drop_index(op.f('ix_ai_conversations_user_id'), table_name='ai_conversations')
    op.drop_table('ai_conversations')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_knowledge_chunks_embedding', table_name='knowledge_chunks', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_knowledge_chunks_document_id'), table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
    op.drop_index('ix_incidents_team_status', table_name='incidents')
    op.drop_index('ix_incidents_status_due', table_name='incidents')
    op.drop_index(op.f('ix_incidents_status'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_sla_breached'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_requester_id'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_priority'), table_name='incidents')
    op.drop_index('ix_incidents_created_at', table_name='incidents')
    op.drop_index(op.f('ix_incidents_category'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_assignee_id'), table_name='incidents')
    op.drop_table('incidents')
    op.drop_index(op.f('ix_users_team_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_knowledge_documents_category'), table_name='knowledge_documents')
    op.drop_table('knowledge_documents')
    op.drop_table('teams')
    op.drop_table('sla_policies')
    op.drop_table('runbooks')
