# Proposals through MCP

An assistant connected to ARGUS through MCP — Claude, ChatGPT, LibreChat, any MCP client — can look things up and
**propose** changes. It never makes one: a person applies or discards each proposal.

## The tools

On `<api>/mcp`, next to the lookups (docs: help page "Account and API tokens"):

| tool | proposes |
|---|---|
| `propose_create_record` | a record of a type of the workspace, with its attributes |
| `propose_update_record` | a change of a record's name or attributes (null clears one) |
| `propose_relation` | a relation between two records, or with `remove` its removal |
| `propose_ticket` | a ticket of a ticket type, on a record, with priority and due date |
| `propose_document` | a draft document of a document type, its Markdown text and the records it describes |

They are described to the client as not read-only, not destructive and not idempotent (MCP tool annotations), so a
client asks its user before calling them. Pull requests are proposed only in Ask ARGUS.

Each call is checked at once, as Ask ARGUS checks its own proposals (`services/ask_actions.py`): the type exists,
the records exist and are visible, the relation is allowed between those types, the attributes are the type's. A
refusal comes back with its reason, so the assistant can correct it. A proposal is accepted only from a caller that
could make the change by hand: a token needs the *Create* scope (*Modify* for a change, *Delete* to remove a
relation) and the matching rights in the workspace.

## Where they wait

A day's proposals of one token or one person in one workspace are kept together (`ask_conversations.source =
"mcp"`, `services/mcp_proposals.py`): a record proposed earlier that day is `new:N` for the next proposals. They are
not Ask ARGUS conversations and do not appear in anybody's Ask history.

They wait in the **Review queue**, under *Proposed by assistants*, and count in its badge. `GET /v1/proposals`
lists them; `POST /v1/proposals/apply` and `/discard` with `{"ids": [...]}` decide — **only a person signed in**,
never a token. Applying runs each change through the same code as the forms, with the permissions of the person
applying and in their name in the ledger and the history; a document becomes a draft that goes through review
and approval like any other. Each change stands or fails on its own, with its error shown.
