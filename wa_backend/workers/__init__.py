"""Wanasah background worker package.

Queue metadata is system-owned. Tenant data must always be accessed through
workers.tenant.tenant_session so PostgreSQL RLS is active before any query.
"""
