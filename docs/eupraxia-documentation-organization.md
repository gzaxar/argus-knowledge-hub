EuPRAXIA Documentation Organization in ARGUS

1\. Purpose and Scope

This document defines the strategy for organizing, migrating, and creating documentation for EuPRAXIA within the ARGUS Knowledge Hub. It establishes the taxonomy, metadata schema, and governance rules required to ensure consistency, discoverability, and effective AI-assisted retrieval (Ask ARGUS).



2\. Guiding Principles

Single Source of Truth: One canonical "document of record" per topic. Links to legacy Confluence pages are allowed, but duplicates are not.

Register-First: Structured data (assets, addresses, port maps) belongs in ARGUS Registers, not in static documents.

Lifecycle-Aware: Every document has a named owner, approver, and status (draft → approved → superseded).

AI-Ready: Content must be structured with clear metadata to support Ask ARGUS.

3\. Mapping EuPRAXIA Templates to ARGUS Types

To maintain uniformity, the official EuPRAXIA templates (M170–M178) map directly to ARGUS native Document Types:



EuPRAXIA Template	ARGUS Document Type	Usage Notes

M170 (Reference)	Specification / Design Report	Use for stable facts, architectures, parameters.

M171 (How-to)	Work Instruction / Procedure	Use for step-by-step tasks with a single goal.

M173 (Commissioning)	Procedure	Requires acceptance criteria and evidence.

M174 (Interface)	Specification	Defines producer/consumer tolerances.

M176 (Record Entry)	Logbook Entry	Entries for the M035 and M075 databases.

M178 (Manual Index)	Manual	Indexes supplier manuals without copying content.

4\. Metadata Schema (Minimum Required Fields)

Every document created in ARGUS must include the following metadata:



Code: Canonical ID (e.g., M030). Override the auto-generated ARGUS code.

Title: Official title matching the Minimum Documentation Set.

Owner / Approver: Named individuals responsible for the content.

Status: draft / in review / approved / superseded.

WP: Work Package identifier (e.g., WP-04, WP-08).

Related Assets: Links to physical assets in the ARGUS Asset module.

5\. Governance Rules

ID Policy: The Mxxx IDs are immutable and must be used as the ARGUS Code.

Owner Rule: No document reaches approved status without a named owner. "TBD" is allowed only in the draft phase.

Register Policy: Documents M030, M036, M077 act as schema definitions. The actual data lives as Register instances in ARGUS.

Record Policy: M035 and M075 are native ARGUS Registers, with entries created as Logbook Entry or Record types.

6\. Rollout Phasing

To ensure a controlled migration, the ARGUS Knowledge Hub will be introduced to EuPRAXIA in three waves:



Wave 1 (Pilot): WP-04 (RF) and WP-08 (Diagnostics \& Timing) Selected for their high complexity in interfaces (M174), strict operational procedures (M171/M173), and data logging (M176). Success here proves the system's capability.

Wave 2 (Expansion): Vacuum and Magnets Highly standardized systems with many physical assets. Ideal for testing the ARGUS Asset Management and Ticketing integrations.

Wave 3 (Full Migration): Remaining WPs Migrated using the standardized templates and metadata schemas established during the pilot phases.

