# Guide: Creating EuPRAXIA Documents in ARGUS

This guide explains how to create standardized, uniform documents for the EuPRAXIA project inside the ARGUS Knowledge Hub. Following these rules ensures that the ARGUS AI (Ask ARGUS) and human users can easily find, understand, and link information.

## 1. Choose the Correct Document Type
Do not create ad-hoc types. Map your EuPRAXIA document templates (M170–M178) to the native ARGUS types as follows:

| EuPRAXIA Template | ARGUS Document Type | When to use it |
| :--- | :--- | :--- |
| **M170** (Reference) | ``Specification`` or ``Design Report`` | Hardware specs, architectures, parameters (e.g., M030 Stations, M076 Timing). |
| **M171** (How-to) | ``Work Instruction`` or ``Procedure`` | Step-by-step tasks (e.g., M039 Modulators ON/OFF). |
| **M173** (Commissioning) | ``Procedure`` | Commissioning steps that require acceptance criteria and evidence. |
| **M174** (Interface) | ``Specification`` | Documents defining producer/consumer tolerances. |
| **M176** (Record Entry) | ``Logbook Entry`` | Entries for the M035 and M075 databases. |
| **M178** (Manual Index) | ``Manual`` | Indexing supplier manuals without copying content. |

## 2. Fill in the Metadata Form
When you click **"+ New"**, fill out the form exactly as follows:
*   **Code:** Do not leave it blank. Override the auto-generated code with the canonical EuPRAXIA ID (e.g., ``M030``, ``M033``).
*   **Type:** Select the type from the table above.
*   **Title:** Use the exact title from the EuPRAXIA Minimum Documentation Set (e.g., ``Stations, zones and PBS codes``).
*   **Authority level:** Set to ``Informative`` for references, ``Operational`` for procedures.
*   **Confidentiality:** Set to ``Interno`` (or as required by WP rules).

## 3. The Standard Document Structure (Markdown Skeletons)
To ensure uniformity, **copy and paste** the appropriate skeleton below into the **Body** section of the editor, and fill in the blanks.

### 3.1 Skeleton for a Reference / Specification (M170)
````markdown
# [Document Title]

## 1. Purpose and Scope
> Describe the purpose of this reference document and its boundaries.

## 2. Definitions and Units
- **Term 1:** Definition
- **Unit 1:** ...

## 3. Content and Parameters
> Insert the core content, tables, and diagrams here.

## 4. Related Interfaces and Documents
- Interface with: 
- Related manual: 

## 5. Review Triggers
> What changes require this document to be reviewed? (e.g., hardware upgrade)
