"""initial schema

Mirrors db/schema.sql plus sprint-2 additions (version_label, red-team detector
columns, jobs.error, fingerprint_signatures, fingerprint_comparisons).

Revision ID: 0001
Revises: 
Create Date: 2026-11-24 07:07:48.928823
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from sentinel.db.models import EmbeddingType

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.create_table('eval_examples',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('input_text', sa.Text(), nullable=False),
    sa.Column('response_text', sa.Text(), nullable=False),
    sa.Column('expected_label', sa.Boolean(), nullable=False),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('owner_email', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('job_type', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jobs_project_id'), ['project_id'], unique=False)

    op.create_table('model_endpoints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('model_identifier', sa.Text(), nullable=False),
    sa.Column('version_label', sa.Text(), nullable=True),
    sa.Column('endpoint_url', sa.Text(), nullable=True),
    sa.Column('credential_ref', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('model_endpoints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_endpoints_project_id'), ['project_id'], unique=False)

    op.create_table('system_prompt_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'version_number')
    )
    with op.batch_alter_table('system_prompt_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_system_prompt_versions_project_id'), ['project_id'], unique=False)

    op.create_table('constraints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('system_prompt_version_id', sa.Uuid(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('weight', sa.Numeric(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['system_prompt_version_id'], ['system_prompt_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('constraints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_constraints_system_prompt_version_id'), ['system_prompt_version_id'], unique=False)

    op.create_table('fingerprint_signatures',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('embedding_model', sa.String(length=200), nullable=False),
    sa.Column('probe_set_version', sa.String(length=50), nullable=False),
    sa.Column('dimension', sa.Integer(), nullable=False),
    sa.Column('centroid', EmbeddingType(), nullable=False),
    sa.Column('probe_embeddings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('stylometrics', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['model_endpoint_id'], ['model_endpoints.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('fingerprint_signatures', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fingerprint_signatures_model_endpoint_id'), ['model_endpoint_id'], unique=False)

    op.create_table('ownership_verifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('verification_token', sa.Text(), nullable=True),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['model_endpoint_id'], ['model_endpoints.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ownership_verifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ownership_verifications_model_endpoint_id'), ['model_endpoint_id'], unique=False)

    op.create_table('test_cases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('attack_type', sa.Text(), nullable=True),
    sa.Column('input_text', sa.Text(), nullable=False),
    sa.Column('attack_succeeded', sa.Boolean(), nullable=True),
    sa.Column('detector_notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('test_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_test_cases_job_id'), ['job_id'], unique=False)

    op.create_table('fingerprint_comparisons',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reference_signature_id', sa.Uuid(), nullable=False),
    sa.Column('candidate_signature_id', sa.Uuid(), nullable=False),
    sa.Column('centroid_similarity', sa.Float(), nullable=False),
    sa.Column('mean_probe_similarity', sa.Float(), nullable=False),
    sa.Column('threshold', sa.Float(), nullable=False),
    sa.Column('likely_clone', sa.Boolean(), nullable=False),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['candidate_signature_id'], ['fingerprint_signatures.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reference_signature_id'], ['fingerprint_signatures.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('model_responses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('test_case_id', sa.Uuid(), nullable=False),
    sa.Column('model_endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('response_text', sa.Text(), nullable=False),
    sa.Column('embedding', EmbeddingType(1536), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['model_endpoint_id'], ['model_endpoints.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['test_case_id'], ['test_cases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('model_responses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_responses_model_endpoint_id'), ['model_endpoint_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_model_responses_test_case_id'), ['test_case_id'], unique=False)

    op.create_table('judge_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('model_response_id', sa.Uuid(), nullable=False),
    sa.Column('judge_model', sa.Text(), nullable=False),
    sa.Column('raw_output', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['model_response_id'], ['model_responses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('judge_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_judge_runs_model_response_id'), ['model_response_id'], unique=False)

    op.create_table('violations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('judge_run_id', sa.Uuid(), nullable=False),
    sa.Column('constraint_id', sa.Uuid(), nullable=False),
    sa.Column('violated', sa.Boolean(), nullable=False),
    sa.Column('evidence_span', sa.Text(), nullable=True),
    sa.Column('reasoning', sa.Text(), nullable=True),
    sa.Column('severity', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['constraint_id'], ['constraints.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['judge_run_id'], ['judge_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('violations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_violations_constraint_id'), ['constraint_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_violations_judge_run_id'), ['judge_run_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('violations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_violations_judge_run_id'))
        batch_op.drop_index(batch_op.f('ix_violations_constraint_id'))

    op.drop_table('violations')
    with op.batch_alter_table('judge_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_judge_runs_model_response_id'))

    op.drop_table('judge_runs')
    with op.batch_alter_table('model_responses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_responses_test_case_id'))
        batch_op.drop_index(batch_op.f('ix_model_responses_model_endpoint_id'))

    op.drop_table('model_responses')
    op.drop_table('fingerprint_comparisons')
    with op.batch_alter_table('test_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_cases_job_id'))

    op.drop_table('test_cases')
    with op.batch_alter_table('ownership_verifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ownership_verifications_model_endpoint_id'))

    op.drop_table('ownership_verifications')
    with op.batch_alter_table('fingerprint_signatures', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fingerprint_signatures_model_endpoint_id'))

    op.drop_table('fingerprint_signatures')
    with op.batch_alter_table('constraints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_constraints_system_prompt_version_id'))

    op.drop_table('constraints')
    with op.batch_alter_table('system_prompt_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_system_prompt_versions_project_id'))

    op.drop_table('system_prompt_versions')
    with op.batch_alter_table('model_endpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_endpoints_project_id'))

    op.drop_table('model_endpoints')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_project_id'))

    op.drop_table('jobs')
    op.drop_table('projects')
    op.drop_table('eval_examples')
