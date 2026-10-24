"""Evaluation source fixtures with planted contradictions and update workload scenarios."""

from typing import Dict, List


# Planted Contradiction Fixtures
CONTRADICTION_FIXTURE_A = """
System Architecture Security Audit Report.
Database port 5432 is publicly accessible for external analytics queries.
The analytics team connects directly over TLS without VPN requirement.
Database system PostgresCluster is maintained by DataOps.
"""

CONTRADICTION_FIXTURE_B = """
Infrastructure Hardening and Compliance Policy.
Database port 5432 is strictly private and blocked by the firewall.
Direct external connections are explicitly prohibited under zero-trust guidelines.
Database system PostgresCluster is monitored by SecurityOps.
"""

CONTRADICTION_FIXTURE_C = """
Release Bulletin 2026-Q3.
Authentication service version 3.2 is deployed in production environment.
The auth microservice handles all OAuth2 authorization flows.
"""

CONTRADICTION_FIXTURE_D = """
Incident Response Notification 2026-Q3.
Authentication service version 3.2 was retracted and deprecated due to critical vulnerability.
Legacy auth microservice version 3.1 remains the sole authorized build.
"""

# Update Fixtures (Changed value, removed relation, new relation, delete-only, shared entity)
UPDATE_DOC_BASE_V1 = """
Payment Gateway Configuration Version 1.
GatewayService uses TLS version 1.2.
GatewayService depends on BillingDatabase.
GatewayService handles Currency USD.
"""

UPDATE_DOC_REVISED_V2 = """
Payment Gateway Configuration Version 2.
GatewayService uses TLS version 1.3.
GatewayService depends on CloudKmsVault.
GatewayService handles Currency EUR.
"""

DELETE_ONLY_DOC = """
Temporary Staging Worker Node Spec.
StagingWorkerNode is ephemeral and will be decommissioned.
StagingWorkerNode uses TempDiskVolume.
"""

SHARED_ENTITY_DOC_A = """
Corporate Network Core.
CoreRouter connects to CentralSwitch.
CentralSwitch routes traffic for PrimaryDataCenter.
"""

SHARED_ENTITY_DOC_B = """
Branch Office Connectivity.
BranchRouter connects to CentralSwitch.
CentralSwitch routes traffic for RegionalOffices.
"""
