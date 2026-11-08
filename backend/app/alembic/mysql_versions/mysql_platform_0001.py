"""Frozen MySQL 5.7 Platform baseline; independent from PostgreSQL history.

All Platform tables, indexes and foreign keys are explicit. Runtime metadata is
never imported here, so future model edits cannot rewrite this baseline.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
import sqlmodel.sql.sqltypes

revision = "mysql_platform_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('capabilitybinding',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('consumer_module', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('aggregate_type', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('aggregate_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('capability_code', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('provider_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('provider_version', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('external_instance_id', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('closed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'consumer_module', 'aggregate_type', 'aggregate_id', 'capability_code', name='uq_capability_binding_aggregate'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('department',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('leader_user_id', sa.Uuid(), nullable=True),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('archived_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_department_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_department_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('dictionaryitem',
    sa.Column('type_id', sa.Uuid(), nullable=False),
    sa.Column('label', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('value', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('color', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('extra_data', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'type_id', 'value', name='uq_dictionaryitem_tenant_type_value'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('dictionarytype',
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_dictionarytype_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_dictionarytype_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('enterpriseoidcauthorizationstate',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('state_hash', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('code_verifier', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('nonce', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('consumed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('enterpriseoidcidentity',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('subject', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'subject', name='uq_enterpriseoidcidentity_provider_subject'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('enterpriseoidcloginticket',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('ticket_hash', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('consumed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('eventdelivery',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('target_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=False),
    sa.Column('consumer_module', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('locked_by', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('locked_until', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('delivered_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('dead_lettered_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('last_error', mysql.MEDIUMTEXT(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', 'target_name', name='uq_event_delivery_target'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('fileasset',
    sa.Column('original_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('stored_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('content_type', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('extension', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('storage_provider', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('storage_path', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('public_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('uploader_id', sa.Uuid(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('filestoragechannel',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('endpoint_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('region', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('bucket', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('access_key_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('secret_access_key', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('object_prefix', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('addressing_style', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('auto_create_bucket', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_filestoragechannel_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('inboxreceipt',
    sa.Column('consumer_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('processed_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.PrimaryKeyConstraint('consumer_name', 'event_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('loginlog',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('failure_reason', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('mailaccount',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('username', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('password', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('host', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('ssl_enable', sa.Boolean(), nullable=False),
    sa.Column('starttls_enable', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_mailaccount_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_mailaccount_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('maillog',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('account_id', sa.Uuid(), nullable=True),
    sa.Column('account_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('account_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('template_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('from_email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('from_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('to_email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('template_params', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('send_status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('sent_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('message_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('send_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('send_message', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('mailtemplate',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('account_id', sa.Uuid(), nullable=True),
    sa.Column('nickname', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('account_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('params', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_mailtemplate_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_mailtemplate_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('menu',
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('route_path', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('route_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('component', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('permission_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('is_visible', sa.Boolean(), nullable=False),
    sa.Column('is_keep_alive', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('moduleregistry',
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('version', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('desired_state', sa.String(length=32), nullable=False),
    sa.Column('observed_state', sa.String(length=32), nullable=False),
    sa.Column('manifest_digest', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('target_revision', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('actual_revision', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('health_details', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('modulestateaudit',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('module_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=True),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('previous_value', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('next_value', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('notice',
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('published_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_notice_id_tenant_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('oauth2accesstoken',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('access_token', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('refresh_token', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('access_token_hash', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True),
    sa.Column('refresh_token_hash', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True),
    sa.Column('refresh_expires_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('token_family_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('user_email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('user_full_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('scopes', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('revoked_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('oauth2authorizationcode',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('code_hash', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('redirect_uri', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
    sa.Column('scopes', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('code_challenge', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('code_challenge_method', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('used_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('oauth2client',
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('client_secret', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('logo', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('access_token_validity_seconds', sa.Integer(), nullable=False),
    sa.Column('refresh_token_validity_seconds', sa.Integer(), nullable=False),
    sa.Column('authorized_grant_types', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('scopes', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('auto_approve_scopes', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('redirect_uris', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('authorities', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('resource_ids', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('additional_information', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_oauth2client_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'client_id', name='uq_oauth2client_tenant_client_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('operationlog',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('module', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('method', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('path', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('request_summary', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('response_summary', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('outboxevent',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('module_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('event_type', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('event_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=True),
    sa.Column('aggregate_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('aggregate_sequence', sa.Integer(), nullable=True),
    sa.Column('payload', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('trace_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('occurred_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('available_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('completed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('dead_lettered_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('post',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('archived_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_post_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_post_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('role',
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('data_scope', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.CheckConstraint("data_scope IN ('all', 'department', 'department_and_children', 'self', 'custom')", name='ck_role_data_scope'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_role_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_role_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('roledatascopedepartment',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('department_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('role_id', 'department_id', 'tenant_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('rolemenu',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('menu_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('role_id', 'menu_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('sitemessagetemplate',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('sender_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('params', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_sitemessagetemplate_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_sitemessagetemplate_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('smschannel',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('signature', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('api_key', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('api_secret', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('callback_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_smschannel_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_smschannel_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('smslog',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('channel_id', sa.Uuid(), nullable=True),
    sa.Column('channel_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('template_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
    sa.Column('template_content', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
    sa.Column('template_params', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('api_template_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('mobile', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('send_status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('sent_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('api_send_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('api_send_message', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('api_request_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('api_serial_no', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('receive_status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('received_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('api_receive_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('api_receive_message', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('smstemplate',
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('content', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('api_template_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('channel_id', sa.Uuid(), nullable=True),
    sa.Column('channel_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('params', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_smstemplate_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_smstemplate_tenant_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('socialclient',
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('social_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('user_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('client_secret', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('agent_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'tenant_id', name='uq_socialclient_id_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'social_type', 'user_type', name='uq_socialclient_tenant_social_type_user_type'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('socialuser',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('openid', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('unionid', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('nickname', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('avatar', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('token', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('raw_token_info', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('raw_user_info', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('social_client_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'type', 'openid', name='uq_socialuser_tenant_type_openid'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('systemsetting',
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('value', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('value_type', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('group', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'key', name='uq_systemsetting_tenant_key'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenant',
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('initialization_template_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantinitializationtemplate',
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('root_department_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('root_department_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('seed_posts', sa.Boolean(), nullable=False),
    sa.Column('seed_dictionaries', sa.Boolean(), nullable=False),
    sa.Column('seed_settings', sa.Boolean(), nullable=False),
    sa.Column('seed_storage_channels', sa.Boolean(), nullable=False),
    sa.Column('seed_message_templates', sa.Boolean(), nullable=False),
    sa.Column('seed_sms_channels', sa.Boolean(), nullable=False),
    sa.Column('seed_mail_accounts', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantmembership',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('department_id', sa.Uuid(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('user_id', 'tenant_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantmodule',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('module_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('tenant_id', 'module_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantmoduleentitlementoverride',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('module_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('effect', sa.String(length=32), nullable=False),
    sa.Column('starts_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('ends_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('operator_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantplan',
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('max_members', sa.Integer(), nullable=True),
    sa.Column('max_file_assets', sa.Integer(), nullable=True),
    sa.Column('max_storage_bytes', sa.BigInteger(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantplanmenu',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('menu_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('plan_id', 'menu_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantplanmodule',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('module_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('plan_id', 'module_code'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantplanprofile',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('package_type', sa.Integer(), nullable=False),
    sa.Column('logo', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('published', sa.Integer(), nullable=False),
    sa.Column('order_num', sa.Integer(), nullable=False),
    sa.Column('subscription_num', sa.Integer(), nullable=False),
    sa.Column('subscription_total_amount', sa.Float(), nullable=False),
    sa.Column('remark', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('plan_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('tenantprofile',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('contact_user_id', sa.Uuid(), nullable=True),
    sa.Column('contact_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('contact_mobile', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
    sa.Column('industry', sa.Integer(), nullable=True),
    sa.Column('tenant_type', sa.Integer(), nullable=True),
    sa.Column('address_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('address_detail', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('qualifications', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('website', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('recharge_amount', sa.Float(), nullable=False),
    sa.Column('payment_amount', sa.Float(), nullable=False),
    sa.Column('balance_amount', sa.Float(), nullable=False),
    sa.Column('account_count', sa.Integer(), nullable=True),
    sa.Column('lifecycle_status', sa.String(length=32), nullable=False),
    sa.Column('lifecycle_status_before_freeze', sa.String(length=32), nullable=True),
    sa.Column('effective_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('trial_ends_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('service_expires_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('frozen_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('frozen_reason', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('owner_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('customer_source', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('follow_up_notes', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('tenant_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('user',
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('mobile', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_superuser', sa.Boolean(), nullable=False),
    sa.Column('full_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('avatar_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hashed_password', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('mfa_enabled', sa.Boolean(), nullable=False),
    sa.Column('mfa_secret_encrypted', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('mfa_recovery_code_hashes', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('mfa_confirmed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('archived_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('anonymized_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('usermessage',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('notice_id', sa.Uuid(), nullable=True),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('template_code', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('sender_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('template_params', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
    sa.Column('type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('read_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('userpost',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('post_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('user_id', 'post_id', 'tenant_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('userrole',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('user_id', 'role_id', 'tenant_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_table('usersession',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('token_jti', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('last_active_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('revoked_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_capabilitybinding_consumer_module'), 'capabilitybinding', ['consumer_module'], unique=False)
    op.create_index(op.f('ix_capabilitybinding_status'), 'capabilitybinding', ['status'], unique=False)
    op.create_index(op.f('ix_capabilitybinding_tenant_id'), 'capabilitybinding', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_department_archived_at'), 'department', ['archived_at'], unique=False)
    op.create_index(op.f('ix_department_code'), 'department', ['code'], unique=False)
    op.create_index(op.f('ix_department_tenant_id'), 'department', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_dictionaryitem_tenant_id'), 'dictionaryitem', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_dictionarytype_code'), 'dictionarytype', ['code'], unique=False)
    op.create_index(op.f('ix_dictionarytype_tenant_id'), 'dictionarytype', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_enterpriseoidcauthorizationstate_state_hash'), 'enterpriseoidcauthorizationstate', ['state_hash'], unique=True)
    op.create_index(op.f('ix_enterpriseoidcidentity_user_id'), 'enterpriseoidcidentity', ['user_id'], unique=False)
    op.create_index(op.f('ix_enterpriseoidcloginticket_ticket_hash'), 'enterpriseoidcloginticket', ['ticket_hash'], unique=True)
    op.create_index(op.f('ix_enterpriseoidcloginticket_user_id'), 'enterpriseoidcloginticket', ['user_id'], unique=False)
    op.create_index(op.f('ix_eventdelivery_available_at'), 'eventdelivery', ['available_at'], unique=False)
    op.create_index(op.f('ix_eventdelivery_consumer_module'), 'eventdelivery', ['consumer_module'], unique=False)
    op.create_index(op.f('ix_eventdelivery_event_id'), 'eventdelivery', ['event_id'], unique=False)
    op.create_index(op.f('ix_eventdelivery_locked_by'), 'eventdelivery', ['locked_by'], unique=False)
    op.create_index(op.f('ix_eventdelivery_locked_until'), 'eventdelivery', ['locked_until'], unique=False)
    op.create_index(op.f('ix_eventdelivery_status'), 'eventdelivery', ['status'], unique=False)
    op.create_index(op.f('ix_eventdelivery_target_type'), 'eventdelivery', ['target_type'], unique=False)
    op.create_index(op.f('ix_fileasset_created_at'), 'fileasset', ['created_at'], unique=False)
    op.create_index(op.f('ix_fileasset_sha256'), 'fileasset', ['sha256'], unique=False)
    op.create_index(op.f('ix_fileasset_tenant_id'), 'fileasset', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_fileasset_uploader_id'), 'fileasset', ['uploader_id'], unique=False)
    op.create_index(op.f('ix_filestoragechannel_code'), 'filestoragechannel', ['code'], unique=False)
    op.create_index(op.f('ix_filestoragechannel_tenant_id'), 'filestoragechannel', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_loginlog_created_at'), 'loginlog', ['created_at'], unique=False)
    op.create_index(op.f('ix_loginlog_email'), 'loginlog', ['email'], unique=False)
    op.create_index(op.f('ix_loginlog_tenant_id'), 'loginlog', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_mailaccount_code'), 'mailaccount', ['code'], unique=False)
    op.create_index(op.f('ix_mailaccount_tenant_id'), 'mailaccount', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_maillog_created_at'), 'maillog', ['created_at'], unique=False)
    op.create_index(op.f('ix_maillog_sent_at'), 'maillog', ['sent_at'], unique=False)
    op.create_index(op.f('ix_maillog_tenant_id'), 'maillog', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_maillog_to_email'), 'maillog', ['to_email'], unique=False)
    op.create_index(op.f('ix_mailtemplate_account_id'), 'mailtemplate', ['account_id'], unique=False)
    op.create_index(op.f('ix_mailtemplate_code'), 'mailtemplate', ['code'], unique=False)
    op.create_index(op.f('ix_mailtemplate_tenant_id'), 'mailtemplate', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_menu_permission_code'), 'menu', ['permission_code'], unique=False)
    op.create_index(op.f('ix_moduleregistry_desired_state'), 'moduleregistry', ['desired_state'], unique=False)
    op.create_index(op.f('ix_moduleregistry_observed_state'), 'moduleregistry', ['observed_state'], unique=False)
    op.create_index(op.f('ix_modulestateaudit_module_code'), 'modulestateaudit', ['module_code'], unique=False)
    op.create_index(op.f('ix_modulestateaudit_tenant_id'), 'modulestateaudit', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_notice_created_at'), 'notice', ['created_at'], unique=False)
    op.create_index(op.f('ix_notice_published_at'), 'notice', ['published_at'], unique=False)
    op.create_index(op.f('ix_notice_status'), 'notice', ['status'], unique=False)
    op.create_index(op.f('ix_notice_tenant_id'), 'notice', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_oauth2accesstoken_access_token'), 'oauth2accesstoken', ['access_token'], unique=True)
    op.create_index(op.f('ix_oauth2accesstoken_access_token_hash'), 'oauth2accesstoken', ['access_token_hash'], unique=True)
    op.create_index(op.f('ix_oauth2accesstoken_client_id'), 'oauth2accesstoken', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth2accesstoken_refresh_token'), 'oauth2accesstoken', ['refresh_token'], unique=False)
    op.create_index(op.f('ix_oauth2accesstoken_refresh_token_hash'), 'oauth2accesstoken', ['refresh_token_hash'], unique=False)
    op.create_index(op.f('ix_oauth2accesstoken_tenant_id'), 'oauth2accesstoken', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_oauth2accesstoken_token_family_id'), 'oauth2accesstoken', ['token_family_id'], unique=False)
    op.create_index(op.f('ix_oauth2accesstoken_user_id'), 'oauth2accesstoken', ['user_id'], unique=False)
    op.create_index(op.f('ix_oauth2authorizationcode_client_id'), 'oauth2authorizationcode', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth2authorizationcode_code_hash'), 'oauth2authorizationcode', ['code_hash'], unique=True)
    op.create_index(op.f('ix_oauth2authorizationcode_tenant_id'), 'oauth2authorizationcode', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_oauth2authorizationcode_user_id'), 'oauth2authorizationcode', ['user_id'], unique=False)
    op.create_index(op.f('ix_oauth2client_client_id'), 'oauth2client', ['client_id'], unique=True)
    op.create_index(op.f('ix_oauth2client_tenant_id'), 'oauth2client', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_operationlog_created_at'), 'operationlog', ['created_at'], unique=False)
    op.create_index(op.f('ix_operationlog_path'), 'operationlog', ['path'], unique=False)
    op.create_index(op.f('ix_operationlog_tenant_id'), 'operationlog', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_operationlog_user_id'), 'operationlog', ['user_id'], unique=False)
    op.create_index(op.f('ix_outboxevent_aggregate_id'), 'outboxevent', ['aggregate_id'], unique=False)
    op.create_index(op.f('ix_outboxevent_aggregate_sequence'), 'outboxevent', ['aggregate_sequence'], unique=False)
    op.create_index(op.f('ix_outboxevent_available_at'), 'outboxevent', ['available_at'], unique=False)
    op.create_index(op.f('ix_outboxevent_event_type'), 'outboxevent', ['event_type'], unique=False)
    op.create_index(op.f('ix_outboxevent_module_code'), 'outboxevent', ['module_code'], unique=False)
    op.create_index(op.f('ix_outboxevent_status'), 'outboxevent', ['status'], unique=False)
    op.create_index(op.f('ix_outboxevent_tenant_id'), 'outboxevent', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_post_archived_at'), 'post', ['archived_at'], unique=False)
    op.create_index(op.f('ix_post_code'), 'post', ['code'], unique=False)
    op.create_index(op.f('ix_post_tenant_id'), 'post', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_role_code'), 'role', ['code'], unique=False)
    op.create_index(op.f('ix_role_tenant_id'), 'role', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_roledatascopedepartment_tenant_id'), 'roledatascopedepartment', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_sitemessagetemplate_code'), 'sitemessagetemplate', ['code'], unique=False)
    op.create_index(op.f('ix_sitemessagetemplate_tenant_id'), 'sitemessagetemplate', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_smschannel_code'), 'smschannel', ['code'], unique=False)
    op.create_index(op.f('ix_smschannel_tenant_id'), 'smschannel', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_smslog_api_request_id'), 'smslog', ['api_request_id'], unique=False)
    op.create_index(op.f('ix_smslog_created_at'), 'smslog', ['created_at'], unique=False)
    op.create_index(op.f('ix_smslog_mobile'), 'smslog', ['mobile'], unique=False)
    op.create_index(op.f('ix_smslog_sent_at'), 'smslog', ['sent_at'], unique=False)
    op.create_index(op.f('ix_smslog_tenant_id'), 'smslog', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_smstemplate_channel_id'), 'smstemplate', ['channel_id'], unique=False)
    op.create_index(op.f('ix_smstemplate_code'), 'smstemplate', ['code'], unique=False)
    op.create_index(op.f('ix_smstemplate_tenant_id'), 'smstemplate', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_socialclient_social_type'), 'socialclient', ['social_type'], unique=False)
    op.create_index(op.f('ix_socialclient_tenant_id'), 'socialclient', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_socialuser_openid'), 'socialuser', ['openid'], unique=False)
    op.create_index(op.f('ix_socialuser_social_client_id'), 'socialuser', ['social_client_id'], unique=False)
    op.create_index(op.f('ix_socialuser_tenant_id'), 'socialuser', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_socialuser_type'), 'socialuser', ['type'], unique=False)
    op.create_index(op.f('ix_socialuser_user_id'), 'socialuser', ['user_id'], unique=False)
    op.create_index(op.f('ix_systemsetting_key'), 'systemsetting', ['key'], unique=False)
    op.create_index(op.f('ix_systemsetting_tenant_id'), 'systemsetting', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tenant_code'), 'tenant', ['code'], unique=True)
    op.create_index(op.f('ix_tenant_initialization_template_id'), 'tenant', ['initialization_template_id'], unique=False)
    op.create_index(op.f('ix_tenant_plan_id'), 'tenant', ['plan_id'], unique=False)
    op.create_index(op.f('ix_tenantinitializationtemplate_code'), 'tenantinitializationtemplate', ['code'], unique=True)
    op.create_index(op.f('ix_tenantmembership_department_id'), 'tenantmembership', ['department_id'], unique=False)
    op.create_index(op.f('ix_tenantmembership_tenant_id'), 'tenantmembership', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tenantmoduleentitlementoverride_ends_at'), 'tenantmoduleentitlementoverride', ['ends_at'], unique=False)
    op.create_index(op.f('ix_tenantmoduleentitlementoverride_module_code'), 'tenantmoduleentitlementoverride', ['module_code'], unique=False)
    op.create_index(op.f('ix_tenantmoduleentitlementoverride_starts_at'), 'tenantmoduleentitlementoverride', ['starts_at'], unique=False)
    op.create_index(op.f('ix_tenantmoduleentitlementoverride_tenant_id'), 'tenantmoduleentitlementoverride', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tenantplan_code'), 'tenantplan', ['code'], unique=True)
    op.create_index(op.f('ix_tenantprofile_customer_source'), 'tenantprofile', ['customer_source'], unique=False)
    op.create_index(op.f('ix_tenantprofile_lifecycle_status'), 'tenantprofile', ['lifecycle_status'], unique=False)
    op.create_index(op.f('ix_tenantprofile_owner_name'), 'tenantprofile', ['owner_name'], unique=False)
    op.create_index(op.f('ix_tenantprofile_service_expires_at'), 'tenantprofile', ['service_expires_at'], unique=False)
    op.create_index(op.f('ix_tenantprofile_trial_ends_at'), 'tenantprofile', ['trial_ends_at'], unique=False)
    op.create_index(op.f('ix_user_anonymized_at'), 'user', ['anonymized_at'], unique=False)
    op.create_index(op.f('ix_user_archived_at'), 'user', ['archived_at'], unique=False)
    op.create_index(op.f('ix_user_email'), 'user', ['email'], unique=True)
    op.create_index(op.f('ix_user_mobile'), 'user', ['mobile'], unique=True)
    op.create_index(op.f('ix_usermessage_created_at'), 'usermessage', ['created_at'], unique=False)
    op.create_index(op.f('ix_usermessage_notice_id'), 'usermessage', ['notice_id'], unique=False)
    op.create_index(op.f('ix_usermessage_template_code'), 'usermessage', ['template_code'], unique=False)
    op.create_index(op.f('ix_usermessage_template_id'), 'usermessage', ['template_id'], unique=False)
    op.create_index(op.f('ix_usermessage_tenant_id'), 'usermessage', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_usermessage_user_id'), 'usermessage', ['user_id'], unique=False)
    op.create_index(op.f('ix_userpost_tenant_id'), 'userpost', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_userrole_tenant_id'), 'userrole', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_usersession_tenant_id'), 'usersession', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_usersession_token_jti'), 'usersession', ['token_jti'], unique=True)
    op.create_index(op.f('ix_usersession_user_id'), 'usersession', ['user_id'], unique=False)
    op.create_foreign_key('fk_capabilitybinding_tenant_id_tenant', 'capabilitybinding', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_department_leader_user_id_tenant_id_tenantmembership', 'department', 'tenantmembership', ['leader_user_id', 'tenant_id'], ['user_id', 'tenant_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_department_parent_id_tenant_id_department', 'department', 'department', ['parent_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_department_tenant_id_tenant', 'department', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_dictionaryitem_tenant_id_tenant', 'dictionaryitem', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_dictionaryitem_type_id_tenant_id_dictionarytype', 'dictionaryitem', 'dictionarytype', ['type_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_dictionarytype_tenant_id_tenant', 'dictionarytype', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_enterpriseoidcidentity_user_id_user', 'enterpriseoidcidentity', 'user', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_enterpriseoidcloginticket_user_id_user', 'enterpriseoidcloginticket', 'user', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_eventdelivery_event_id_outboxevent', 'eventdelivery', 'outboxevent', ['event_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_fileasset_tenant_id_tenant', 'fileasset', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_filestoragechannel_tenant_id_tenant', 'filestoragechannel', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_inboxreceipt_event_id_outboxevent', 'inboxreceipt', 'outboxevent', ['event_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_loginlog_tenant_id_tenant', 'loginlog', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_mailaccount_tenant_id_tenant', 'mailaccount', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_maillog_account_id_tenant_id_mailaccount', 'maillog', 'mailaccount', ['account_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_maillog_template_id_tenant_id_mailtemplate', 'maillog', 'mailtemplate', ['template_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_maillog_tenant_id_tenant', 'maillog', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_mailtemplate_account_id_tenant_id_mailaccount', 'mailtemplate', 'mailaccount', ['account_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_mailtemplate_tenant_id_tenant', 'mailtemplate', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_menu_parent_id_menu', 'menu', 'menu', ['parent_id'], ['id'])
    op.create_foreign_key('fk_modulestateaudit_actor_user_id_user', 'modulestateaudit', 'user', ['actor_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_modulestateaudit_tenant_id_tenant', 'modulestateaudit', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_notice_created_by_user', 'notice', 'user', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_notice_tenant_id_tenant', 'notice', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_oauth2accesstoken_client_id_tenant_id_oauth2client', 'oauth2accesstoken', 'oauth2client', ['tenant_id', 'client_id'], ['tenant_id', 'client_id'])
    op.create_foreign_key('fk_oauth2accesstoken_tenant_id_tenant', 'oauth2accesstoken', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_oauth2accesstoken_user_id_user', 'oauth2accesstoken', 'user', ['user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_oauth2authorizationcode_client_id_tenant_id_oauth2client', 'oauth2authorizationcode', 'oauth2client', ['tenant_id', 'client_id'], ['tenant_id', 'client_id'])
    op.create_foreign_key('fk_oauth2authorizationcode_tenant_id_tenant', 'oauth2authorizationcode', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_oauth2authorizationcode_user_id_user', 'oauth2authorizationcode', 'user', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_oauth2client_tenant_id_tenant', 'oauth2client', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_operationlog_tenant_id_tenant', 'operationlog', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_outboxevent_tenant_id_tenant', 'outboxevent', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_post_tenant_id_tenant', 'post', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_role_tenant_id_tenant', 'role', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_roledatascopedepartment_department_id_tenant_id_department', 'roledatascopedepartment', 'department', ['department_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_roledatascopedepartment_role_id_tenant_id_role', 'roledatascopedepartment', 'role', ['role_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_rolemenu_menu_id_menu', 'rolemenu', 'menu', ['menu_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_rolemenu_role_id_role', 'rolemenu', 'role', ['role_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_sitemessagetemplate_tenant_id_tenant', 'sitemessagetemplate', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_smschannel_tenant_id_tenant', 'smschannel', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_smslog_channel_id_tenant_id_smschannel', 'smslog', 'smschannel', ['channel_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_smslog_template_id_tenant_id_smstemplate', 'smslog', 'smstemplate', ['template_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_smslog_tenant_id_tenant', 'smslog', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_smstemplate_channel_id_tenant_id_smschannel', 'smstemplate', 'smschannel', ['channel_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_smstemplate_tenant_id_tenant', 'smstemplate', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_socialclient_tenant_id_tenant', 'socialclient', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_socialuser_social_client_id_socialclient', 'socialuser', 'socialclient', ['social_client_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_socialuser_social_client_id_tenant_id_socialclient', 'socialuser', 'socialclient', ['social_client_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_socialuser_tenant_id_tenant', 'socialuser', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_socialuser_user_id_user', 'socialuser', 'user', ['user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_socialuser_user_id_tenant_id_tenantmembership', 'socialuser', 'tenantmembership', ['user_id', 'tenant_id'], ['user_id', 'tenant_id'])
    op.create_foreign_key('fk_systemsetting_tenant_id_tenant', 'systemsetting', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenant_initialization_template_id_tenantinitializa_e24cf7700a', 'tenant', 'tenantinitializationtemplate', ['initialization_template_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_tenant_plan_id_tenantplan', 'tenant', 'tenantplan', ['plan_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_tenantmembership_department_id_tenant_id_department', 'tenantmembership', 'department', ['department_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_tenantmembership_tenant_id_tenant', 'tenantmembership', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantmembership_user_id_user', 'tenantmembership', 'user', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantmodule_tenant_id_tenant', 'tenantmodule', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantmoduleentitlementoverride_operator_user_id_user', 'tenantmoduleentitlementoverride', 'user', ['operator_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_tenantmoduleentitlementoverride_tenant_id_tenant', 'tenantmoduleentitlementoverride', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantplanmenu_menu_id_menu', 'tenantplanmenu', 'menu', ['menu_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantplanmenu_plan_id_tenantplan', 'tenantplanmenu', 'tenantplan', ['plan_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantplanmodule_plan_id_tenantplan', 'tenantplanmodule', 'tenantplan', ['plan_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantplanprofile_plan_id_tenantplan', 'tenantplanprofile', 'tenantplan', ['plan_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_tenantprofile_contact_user_id_user', 'tenantprofile', 'user', ['contact_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_tenantprofile_tenant_id_tenant', 'tenantprofile', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_usermessage_notice_id_tenant_id_notice', 'usermessage', 'notice', ['notice_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_usermessage_template_id_tenant_id_sitemessagetemplate', 'usermessage', 'sitemessagetemplate', ['template_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_foreign_key('fk_usermessage_tenant_id_tenant', 'usermessage', 'tenant', ['tenant_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_usermessage_user_id_tenant_id_tenantmembership', 'usermessage', 'tenantmembership', ['user_id', 'tenant_id'], ['user_id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_userpost_post_id_tenant_id_post', 'userpost', 'post', ['post_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_userpost_user_id_tenant_id_tenantmembership', 'userpost', 'tenantmembership', ['user_id', 'tenant_id'], ['user_id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_userrole_role_id_tenant_id_role', 'userrole', 'role', ['role_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_userrole_user_id_tenant_id_tenantmembership', 'userrole', 'tenantmembership', ['user_id', 'tenant_id'], ['user_id', 'tenant_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_usersession_tenant_id_tenant', 'usersession', 'tenant', ['tenant_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_usersession_user_id_user', 'usersession', 'user', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade():
    op.drop_constraint('fk_usersession_user_id_user', 'usersession', type_='foreignkey')
    op.drop_constraint('fk_usersession_tenant_id_tenant', 'usersession', type_='foreignkey')
    op.drop_constraint('fk_userrole_user_id_tenant_id_tenantmembership', 'userrole', type_='foreignkey')
    op.drop_constraint('fk_userrole_role_id_tenant_id_role', 'userrole', type_='foreignkey')
    op.drop_constraint('fk_userpost_user_id_tenant_id_tenantmembership', 'userpost', type_='foreignkey')
    op.drop_constraint('fk_userpost_post_id_tenant_id_post', 'userpost', type_='foreignkey')
    op.drop_constraint('fk_usermessage_user_id_tenant_id_tenantmembership', 'usermessage', type_='foreignkey')
    op.drop_constraint('fk_usermessage_tenant_id_tenant', 'usermessage', type_='foreignkey')
    op.drop_constraint('fk_usermessage_template_id_tenant_id_sitemessagetemplate', 'usermessage', type_='foreignkey')
    op.drop_constraint('fk_usermessage_notice_id_tenant_id_notice', 'usermessage', type_='foreignkey')
    op.drop_constraint('fk_tenantprofile_tenant_id_tenant', 'tenantprofile', type_='foreignkey')
    op.drop_constraint('fk_tenantprofile_contact_user_id_user', 'tenantprofile', type_='foreignkey')
    op.drop_constraint('fk_tenantplanprofile_plan_id_tenantplan', 'tenantplanprofile', type_='foreignkey')
    op.drop_constraint('fk_tenantplanmodule_plan_id_tenantplan', 'tenantplanmodule', type_='foreignkey')
    op.drop_constraint('fk_tenantplanmenu_plan_id_tenantplan', 'tenantplanmenu', type_='foreignkey')
    op.drop_constraint('fk_tenantplanmenu_menu_id_menu', 'tenantplanmenu', type_='foreignkey')
    op.drop_constraint('fk_tenantmoduleentitlementoverride_tenant_id_tenant', 'tenantmoduleentitlementoverride', type_='foreignkey')
    op.drop_constraint('fk_tenantmoduleentitlementoverride_operator_user_id_user', 'tenantmoduleentitlementoverride', type_='foreignkey')
    op.drop_constraint('fk_tenantmodule_tenant_id_tenant', 'tenantmodule', type_='foreignkey')
    op.drop_constraint('fk_tenantmembership_user_id_user', 'tenantmembership', type_='foreignkey')
    op.drop_constraint('fk_tenantmembership_tenant_id_tenant', 'tenantmembership', type_='foreignkey')
    op.drop_constraint('fk_tenantmembership_department_id_tenant_id_department', 'tenantmembership', type_='foreignkey')
    op.drop_constraint('fk_tenant_plan_id_tenantplan', 'tenant', type_='foreignkey')
    op.drop_constraint('fk_tenant_initialization_template_id_tenantinitializa_e24cf7700a', 'tenant', type_='foreignkey')
    op.drop_constraint('fk_systemsetting_tenant_id_tenant', 'systemsetting', type_='foreignkey')
    op.drop_constraint('fk_socialuser_user_id_tenant_id_tenantmembership', 'socialuser', type_='foreignkey')
    op.drop_constraint('fk_socialuser_user_id_user', 'socialuser', type_='foreignkey')
    op.drop_constraint('fk_socialuser_tenant_id_tenant', 'socialuser', type_='foreignkey')
    op.drop_constraint('fk_socialuser_social_client_id_tenant_id_socialclient', 'socialuser', type_='foreignkey')
    op.drop_constraint('fk_socialuser_social_client_id_socialclient', 'socialuser', type_='foreignkey')
    op.drop_constraint('fk_socialclient_tenant_id_tenant', 'socialclient', type_='foreignkey')
    op.drop_constraint('fk_smstemplate_tenant_id_tenant', 'smstemplate', type_='foreignkey')
    op.drop_constraint('fk_smstemplate_channel_id_tenant_id_smschannel', 'smstemplate', type_='foreignkey')
    op.drop_constraint('fk_smslog_tenant_id_tenant', 'smslog', type_='foreignkey')
    op.drop_constraint('fk_smslog_template_id_tenant_id_smstemplate', 'smslog', type_='foreignkey')
    op.drop_constraint('fk_smslog_channel_id_tenant_id_smschannel', 'smslog', type_='foreignkey')
    op.drop_constraint('fk_smschannel_tenant_id_tenant', 'smschannel', type_='foreignkey')
    op.drop_constraint('fk_sitemessagetemplate_tenant_id_tenant', 'sitemessagetemplate', type_='foreignkey')
    op.drop_constraint('fk_rolemenu_role_id_role', 'rolemenu', type_='foreignkey')
    op.drop_constraint('fk_rolemenu_menu_id_menu', 'rolemenu', type_='foreignkey')
    op.drop_constraint('fk_roledatascopedepartment_role_id_tenant_id_role', 'roledatascopedepartment', type_='foreignkey')
    op.drop_constraint('fk_roledatascopedepartment_department_id_tenant_id_department', 'roledatascopedepartment', type_='foreignkey')
    op.drop_constraint('fk_role_tenant_id_tenant', 'role', type_='foreignkey')
    op.drop_constraint('fk_post_tenant_id_tenant', 'post', type_='foreignkey')
    op.drop_constraint('fk_outboxevent_tenant_id_tenant', 'outboxevent', type_='foreignkey')
    op.drop_constraint('fk_operationlog_tenant_id_tenant', 'operationlog', type_='foreignkey')
    op.drop_constraint('fk_oauth2client_tenant_id_tenant', 'oauth2client', type_='foreignkey')
    op.drop_constraint('fk_oauth2authorizationcode_user_id_user', 'oauth2authorizationcode', type_='foreignkey')
    op.drop_constraint('fk_oauth2authorizationcode_tenant_id_tenant', 'oauth2authorizationcode', type_='foreignkey')
    op.drop_constraint('fk_oauth2authorizationcode_client_id_tenant_id_oauth2client', 'oauth2authorizationcode', type_='foreignkey')
    op.drop_constraint('fk_oauth2accesstoken_user_id_user', 'oauth2accesstoken', type_='foreignkey')
    op.drop_constraint('fk_oauth2accesstoken_tenant_id_tenant', 'oauth2accesstoken', type_='foreignkey')
    op.drop_constraint('fk_oauth2accesstoken_client_id_tenant_id_oauth2client', 'oauth2accesstoken', type_='foreignkey')
    op.drop_constraint('fk_notice_tenant_id_tenant', 'notice', type_='foreignkey')
    op.drop_constraint('fk_notice_created_by_user', 'notice', type_='foreignkey')
    op.drop_constraint('fk_modulestateaudit_tenant_id_tenant', 'modulestateaudit', type_='foreignkey')
    op.drop_constraint('fk_modulestateaudit_actor_user_id_user', 'modulestateaudit', type_='foreignkey')
    op.drop_constraint('fk_menu_parent_id_menu', 'menu', type_='foreignkey')
    op.drop_constraint('fk_mailtemplate_tenant_id_tenant', 'mailtemplate', type_='foreignkey')
    op.drop_constraint('fk_mailtemplate_account_id_tenant_id_mailaccount', 'mailtemplate', type_='foreignkey')
    op.drop_constraint('fk_maillog_tenant_id_tenant', 'maillog', type_='foreignkey')
    op.drop_constraint('fk_maillog_template_id_tenant_id_mailtemplate', 'maillog', type_='foreignkey')
    op.drop_constraint('fk_maillog_account_id_tenant_id_mailaccount', 'maillog', type_='foreignkey')
    op.drop_constraint('fk_mailaccount_tenant_id_tenant', 'mailaccount', type_='foreignkey')
    op.drop_constraint('fk_loginlog_tenant_id_tenant', 'loginlog', type_='foreignkey')
    op.drop_constraint('fk_inboxreceipt_event_id_outboxevent', 'inboxreceipt', type_='foreignkey')
    op.drop_constraint('fk_filestoragechannel_tenant_id_tenant', 'filestoragechannel', type_='foreignkey')
    op.drop_constraint('fk_fileasset_tenant_id_tenant', 'fileasset', type_='foreignkey')
    op.drop_constraint('fk_eventdelivery_event_id_outboxevent', 'eventdelivery', type_='foreignkey')
    op.drop_constraint('fk_enterpriseoidcloginticket_user_id_user', 'enterpriseoidcloginticket', type_='foreignkey')
    op.drop_constraint('fk_enterpriseoidcidentity_user_id_user', 'enterpriseoidcidentity', type_='foreignkey')
    op.drop_constraint('fk_dictionarytype_tenant_id_tenant', 'dictionarytype', type_='foreignkey')
    op.drop_constraint('fk_dictionaryitem_type_id_tenant_id_dictionarytype', 'dictionaryitem', type_='foreignkey')
    op.drop_constraint('fk_dictionaryitem_tenant_id_tenant', 'dictionaryitem', type_='foreignkey')
    op.drop_constraint('fk_department_tenant_id_tenant', 'department', type_='foreignkey')
    op.drop_constraint('fk_department_parent_id_tenant_id_department', 'department', type_='foreignkey')
    op.drop_constraint('fk_department_leader_user_id_tenant_id_tenantmembership', 'department', type_='foreignkey')
    op.drop_constraint('fk_capabilitybinding_tenant_id_tenant', 'capabilitybinding', type_='foreignkey')
    op.drop_index(op.f('ix_usersession_user_id'), table_name='usersession')
    op.drop_index(op.f('ix_usersession_token_jti'), table_name='usersession')
    op.drop_index(op.f('ix_usersession_tenant_id'), table_name='usersession')
    op.drop_index(op.f('ix_userrole_tenant_id'), table_name='userrole')
    op.drop_index(op.f('ix_userpost_tenant_id'), table_name='userpost')
    op.drop_index(op.f('ix_usermessage_user_id'), table_name='usermessage')
    op.drop_index(op.f('ix_usermessage_tenant_id'), table_name='usermessage')
    op.drop_index(op.f('ix_usermessage_template_id'), table_name='usermessage')
    op.drop_index(op.f('ix_usermessage_template_code'), table_name='usermessage')
    op.drop_index(op.f('ix_usermessage_notice_id'), table_name='usermessage')
    op.drop_index(op.f('ix_usermessage_created_at'), table_name='usermessage')
    op.drop_index(op.f('ix_user_mobile'), table_name='user')
    op.drop_index(op.f('ix_user_email'), table_name='user')
    op.drop_index(op.f('ix_user_archived_at'), table_name='user')
    op.drop_index(op.f('ix_user_anonymized_at'), table_name='user')
    op.drop_index(op.f('ix_tenantprofile_trial_ends_at'), table_name='tenantprofile')
    op.drop_index(op.f('ix_tenantprofile_service_expires_at'), table_name='tenantprofile')
    op.drop_index(op.f('ix_tenantprofile_owner_name'), table_name='tenantprofile')
    op.drop_index(op.f('ix_tenantprofile_lifecycle_status'), table_name='tenantprofile')
    op.drop_index(op.f('ix_tenantprofile_customer_source'), table_name='tenantprofile')
    op.drop_index(op.f('ix_tenantplan_code'), table_name='tenantplan')
    op.drop_index(op.f('ix_tenantmoduleentitlementoverride_tenant_id'), table_name='tenantmoduleentitlementoverride')
    op.drop_index(op.f('ix_tenantmoduleentitlementoverride_starts_at'), table_name='tenantmoduleentitlementoverride')
    op.drop_index(op.f('ix_tenantmoduleentitlementoverride_module_code'), table_name='tenantmoduleentitlementoverride')
    op.drop_index(op.f('ix_tenantmoduleentitlementoverride_ends_at'), table_name='tenantmoduleentitlementoverride')
    op.drop_index(op.f('ix_tenantmembership_tenant_id'), table_name='tenantmembership')
    op.drop_index(op.f('ix_tenantmembership_department_id'), table_name='tenantmembership')
    op.drop_index(op.f('ix_tenantinitializationtemplate_code'), table_name='tenantinitializationtemplate')
    op.drop_index(op.f('ix_tenant_plan_id'), table_name='tenant')
    op.drop_index(op.f('ix_tenant_initialization_template_id'), table_name='tenant')
    op.drop_index(op.f('ix_tenant_code'), table_name='tenant')
    op.drop_index(op.f('ix_systemsetting_tenant_id'), table_name='systemsetting')
    op.drop_index(op.f('ix_systemsetting_key'), table_name='systemsetting')
    op.drop_index(op.f('ix_socialuser_user_id'), table_name='socialuser')
    op.drop_index(op.f('ix_socialuser_type'), table_name='socialuser')
    op.drop_index(op.f('ix_socialuser_tenant_id'), table_name='socialuser')
    op.drop_index(op.f('ix_socialuser_social_client_id'), table_name='socialuser')
    op.drop_index(op.f('ix_socialuser_openid'), table_name='socialuser')
    op.drop_index(op.f('ix_socialclient_tenant_id'), table_name='socialclient')
    op.drop_index(op.f('ix_socialclient_social_type'), table_name='socialclient')
    op.drop_index(op.f('ix_smstemplate_tenant_id'), table_name='smstemplate')
    op.drop_index(op.f('ix_smstemplate_code'), table_name='smstemplate')
    op.drop_index(op.f('ix_smstemplate_channel_id'), table_name='smstemplate')
    op.drop_index(op.f('ix_smslog_tenant_id'), table_name='smslog')
    op.drop_index(op.f('ix_smslog_sent_at'), table_name='smslog')
    op.drop_index(op.f('ix_smslog_mobile'), table_name='smslog')
    op.drop_index(op.f('ix_smslog_created_at'), table_name='smslog')
    op.drop_index(op.f('ix_smslog_api_request_id'), table_name='smslog')
    op.drop_index(op.f('ix_smschannel_tenant_id'), table_name='smschannel')
    op.drop_index(op.f('ix_smschannel_code'), table_name='smschannel')
    op.drop_index(op.f('ix_sitemessagetemplate_tenant_id'), table_name='sitemessagetemplate')
    op.drop_index(op.f('ix_sitemessagetemplate_code'), table_name='sitemessagetemplate')
    op.drop_index(op.f('ix_roledatascopedepartment_tenant_id'), table_name='roledatascopedepartment')
    op.drop_index(op.f('ix_role_tenant_id'), table_name='role')
    op.drop_index(op.f('ix_role_code'), table_name='role')
    op.drop_index(op.f('ix_post_tenant_id'), table_name='post')
    op.drop_index(op.f('ix_post_code'), table_name='post')
    op.drop_index(op.f('ix_post_archived_at'), table_name='post')
    op.drop_index(op.f('ix_outboxevent_tenant_id'), table_name='outboxevent')
    op.drop_index(op.f('ix_outboxevent_status'), table_name='outboxevent')
    op.drop_index(op.f('ix_outboxevent_module_code'), table_name='outboxevent')
    op.drop_index(op.f('ix_outboxevent_event_type'), table_name='outboxevent')
    op.drop_index(op.f('ix_outboxevent_available_at'), table_name='outboxevent')
    op.drop_index(op.f('ix_outboxevent_aggregate_sequence'), table_name='outboxevent')
    op.drop_index(op.f('ix_outboxevent_aggregate_id'), table_name='outboxevent')
    op.drop_index(op.f('ix_operationlog_user_id'), table_name='operationlog')
    op.drop_index(op.f('ix_operationlog_tenant_id'), table_name='operationlog')
    op.drop_index(op.f('ix_operationlog_path'), table_name='operationlog')
    op.drop_index(op.f('ix_operationlog_created_at'), table_name='operationlog')
    op.drop_index(op.f('ix_oauth2client_tenant_id'), table_name='oauth2client')
    op.drop_index(op.f('ix_oauth2client_client_id'), table_name='oauth2client')
    op.drop_index(op.f('ix_oauth2authorizationcode_user_id'), table_name='oauth2authorizationcode')
    op.drop_index(op.f('ix_oauth2authorizationcode_tenant_id'), table_name='oauth2authorizationcode')
    op.drop_index(op.f('ix_oauth2authorizationcode_code_hash'), table_name='oauth2authorizationcode')
    op.drop_index(op.f('ix_oauth2authorizationcode_client_id'), table_name='oauth2authorizationcode')
    op.drop_index(op.f('ix_oauth2accesstoken_user_id'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_token_family_id'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_tenant_id'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_refresh_token_hash'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_refresh_token'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_client_id'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_access_token_hash'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_oauth2accesstoken_access_token'), table_name='oauth2accesstoken')
    op.drop_index(op.f('ix_notice_tenant_id'), table_name='notice')
    op.drop_index(op.f('ix_notice_status'), table_name='notice')
    op.drop_index(op.f('ix_notice_published_at'), table_name='notice')
    op.drop_index(op.f('ix_notice_created_at'), table_name='notice')
    op.drop_index(op.f('ix_modulestateaudit_tenant_id'), table_name='modulestateaudit')
    op.drop_index(op.f('ix_modulestateaudit_module_code'), table_name='modulestateaudit')
    op.drop_index(op.f('ix_moduleregistry_observed_state'), table_name='moduleregistry')
    op.drop_index(op.f('ix_moduleregistry_desired_state'), table_name='moduleregistry')
    op.drop_index(op.f('ix_menu_permission_code'), table_name='menu')
    op.drop_index(op.f('ix_mailtemplate_tenant_id'), table_name='mailtemplate')
    op.drop_index(op.f('ix_mailtemplate_code'), table_name='mailtemplate')
    op.drop_index(op.f('ix_mailtemplate_account_id'), table_name='mailtemplate')
    op.drop_index(op.f('ix_maillog_to_email'), table_name='maillog')
    op.drop_index(op.f('ix_maillog_tenant_id'), table_name='maillog')
    op.drop_index(op.f('ix_maillog_sent_at'), table_name='maillog')
    op.drop_index(op.f('ix_maillog_created_at'), table_name='maillog')
    op.drop_index(op.f('ix_mailaccount_tenant_id'), table_name='mailaccount')
    op.drop_index(op.f('ix_mailaccount_code'), table_name='mailaccount')
    op.drop_index(op.f('ix_loginlog_tenant_id'), table_name='loginlog')
    op.drop_index(op.f('ix_loginlog_email'), table_name='loginlog')
    op.drop_index(op.f('ix_loginlog_created_at'), table_name='loginlog')
    op.drop_index(op.f('ix_filestoragechannel_tenant_id'), table_name='filestoragechannel')
    op.drop_index(op.f('ix_filestoragechannel_code'), table_name='filestoragechannel')
    op.drop_index(op.f('ix_fileasset_uploader_id'), table_name='fileasset')
    op.drop_index(op.f('ix_fileasset_tenant_id'), table_name='fileasset')
    op.drop_index(op.f('ix_fileasset_sha256'), table_name='fileasset')
    op.drop_index(op.f('ix_fileasset_created_at'), table_name='fileasset')
    op.drop_index(op.f('ix_eventdelivery_target_type'), table_name='eventdelivery')
    op.drop_index(op.f('ix_eventdelivery_status'), table_name='eventdelivery')
    op.drop_index(op.f('ix_eventdelivery_locked_until'), table_name='eventdelivery')
    op.drop_index(op.f('ix_eventdelivery_locked_by'), table_name='eventdelivery')
    op.drop_index(op.f('ix_eventdelivery_event_id'), table_name='eventdelivery')
    op.drop_index(op.f('ix_eventdelivery_consumer_module'), table_name='eventdelivery')
    op.drop_index(op.f('ix_eventdelivery_available_at'), table_name='eventdelivery')
    op.drop_index(op.f('ix_enterpriseoidcloginticket_user_id'), table_name='enterpriseoidcloginticket')
    op.drop_index(op.f('ix_enterpriseoidcloginticket_ticket_hash'), table_name='enterpriseoidcloginticket')
    op.drop_index(op.f('ix_enterpriseoidcidentity_user_id'), table_name='enterpriseoidcidentity')
    op.drop_index(op.f('ix_enterpriseoidcauthorizationstate_state_hash'), table_name='enterpriseoidcauthorizationstate')
    op.drop_index(op.f('ix_dictionarytype_tenant_id'), table_name='dictionarytype')
    op.drop_index(op.f('ix_dictionarytype_code'), table_name='dictionarytype')
    op.drop_index(op.f('ix_dictionaryitem_tenant_id'), table_name='dictionaryitem')
    op.drop_index(op.f('ix_department_tenant_id'), table_name='department')
    op.drop_index(op.f('ix_department_code'), table_name='department')
    op.drop_index(op.f('ix_department_archived_at'), table_name='department')
    op.drop_index(op.f('ix_capabilitybinding_tenant_id'), table_name='capabilitybinding')
    op.drop_index(op.f('ix_capabilitybinding_status'), table_name='capabilitybinding')
    op.drop_index(op.f('ix_capabilitybinding_consumer_module'), table_name='capabilitybinding')
    op.drop_table('usersession')
    op.drop_table('userrole')
    op.drop_table('userpost')
    op.drop_table('usermessage')
    op.drop_table('user')
    op.drop_table('tenantprofile')
    op.drop_table('tenantplanprofile')
    op.drop_table('tenantplanmodule')
    op.drop_table('tenantplanmenu')
    op.drop_table('tenantplan')
    op.drop_table('tenantmoduleentitlementoverride')
    op.drop_table('tenantmodule')
    op.drop_table('tenantmembership')
    op.drop_table('tenantinitializationtemplate')
    op.drop_table('tenant')
    op.drop_table('systemsetting')
    op.drop_table('socialuser')
    op.drop_table('socialclient')
    op.drop_table('smstemplate')
    op.drop_table('smslog')
    op.drop_table('smschannel')
    op.drop_table('sitemessagetemplate')
    op.drop_table('rolemenu')
    op.drop_table('roledatascopedepartment')
    op.drop_table('role')
    op.drop_table('post')
    op.drop_table('outboxevent')
    op.drop_table('operationlog')
    op.drop_table('oauth2client')
    op.drop_table('oauth2authorizationcode')
    op.drop_table('oauth2accesstoken')
    op.drop_table('notice')
    op.drop_table('modulestateaudit')
    op.drop_table('moduleregistry')
    op.drop_table('menu')
    op.drop_table('mailtemplate')
    op.drop_table('maillog')
    op.drop_table('mailaccount')
    op.drop_table('loginlog')
    op.drop_table('inboxreceipt')
    op.drop_table('filestoragechannel')
    op.drop_table('fileasset')
    op.drop_table('eventdelivery')
    op.drop_table('enterpriseoidcloginticket')
    op.drop_table('enterpriseoidcidentity')
    op.drop_table('enterpriseoidcauthorizationstate')
    op.drop_table('dictionarytype')
    op.drop_table('dictionaryitem')
    op.drop_table('department')
    op.drop_table('capabilitybinding')
