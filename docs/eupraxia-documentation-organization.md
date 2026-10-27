---
title: EuPRAXIA Document Creation Guide
summary: Instructions for creating standardized EuPRAXIA documents using ARGUS native types and templates.
keywords: ["eupraxia", "documentation", "templates", "how-to", "guide"]
--- 

# EuPRAXIA Documentation Organization in ARGUS

## 1. Purpose and Scope
This document defines the strategy for organizing, migrating, and creating documentation for EuPRAXIA within the ARGUS Knowledge Hub. It establishes the taxonomy, metadata schema, and governance rules required to ensure consistency, discoverability, and effective AI-assisted retrieval (Ask ARGUS).

## 2. Guiding Principles
- **Single Source of Truth:** One canonical "document of record" per topic. Links to legacy Confluence pages are allowed, but duplicates are not.
- **Register-First:** Structured data (assets, addresses, port maps) belongs in ARGUS Registers, not in static documents.
- **Lifecycle-Aware:** Every document has a named owner, approver, and status (draft → approved → superseded).
- **AI-Ready:** Content must be structured with clear metadata to support Ask ARGUS.

## 3. Native ARGUS Document Types for EuPRAXIA
To ensure consistency and fully leverage ARGUS's native capabilities (including AI search and relationship mapping), we will not use custom or legacy document codes. Instead, all EuPRAXIA documentation will be created using the standard ARGUS Document Types.

When creating a document, users should select the appropriate ARGUS Type based on the content:

| ARGUS Document Type | When to use it in EuPRAXIA |
| :--- | :--- |
| **Specification** | For stable facts, parameters, and hardware/software architectures (e.g., RF equipment specs, Timing architectures). |
| **Design Report** | For broader system overviews, block diagrams, and conceptual designs. |
| **Work Instruction** | For short, single-goal step-by-step tasks (e.g., turning modulators on/off). |
| **Procedure** | For complex workflows requiring acceptance criteria, safety checks, and evidence (e.g., commissioning an RF station). |
| **Logbook Entry** | For daily operational logs, acceptance records, and calibration entries. |
| **Manual** | To index supplier/vendor manuals without duplicating their content. |

> **Note on Document Codes:** ARGUS automatically assigns a unique code based on the Document Type (e.g., `SPEC-0001` for Specifications, `PROC-0001` for Procedures). Users should leave the "Code" field blank to allow the system to generate it, ensuring a clean and scalable database.

## 4. Metadata Schema (Minimum Required Fields)
Every document created in ARGUS must include the following metadata:
- **Code:** Leave blank to allow ARGUS to auto-generate it based on the Type.
- **Title:** Official, descriptive title of the document.
- **Owner / Approver:** Named individuals responsible for the content.
- **Status:** draft / in review / approved / superseded.
- **WP:** Work Package identifier (e.g., WP-04, WP-08) written in the Body or Tags.
- **Related Assets:** Links to physical assets in the ARGUS Asset module.

## 5. Governance Rules
- **Code Policy:** Do not use legacy or external codes. Rely on ARGUS's native auto-generated codes.
- **Owner Rule:** No document reaches `approved` status without a named owner. "TBD" is allowed only in the `draft` phase.
- **Register Policy:** Structural data (e.g., Station maps, Power Supply address tables, Optical Fanout port maps) must be created as native ARGUS **Register** instances, not as static documents.
- **Record Policy:** Operational logs (e.g., RF conditioning logs, Diagnostics/Timing calibration records) must be created as native ARGUS **Logbook Entries** or **Records**.

## 6. Rollout Phasing
To ensure a controlled migration, the ARGUS Knowledge Hub will be introduced to EuPRAXIA in three waves:

- **Wave 1 (Pilot): WP-04 (RF) and WP-08 (Diagnostics & Timing)**
  Selected for their high complexity in interfaces, strict operational procedures, and data logging. Success here proves the system's capability.
- **Wave 2 (Expansion): Vacuum and Magnets**
  Highly standardized systems with many physical assets. Ideal for testing the ARGUS Asset Management and Ticketing integrations.
- **Wave 3 (Full Migration): Remaining WPs**
  Migrated using the standardized templates and metadata schemas established during the pilot phases.
