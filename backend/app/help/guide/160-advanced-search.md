---
title: Advanced query
summary: Selecting tickets, equipment and documents with a query — fields, operators, dates, functions, ordering, and searching several workspaces.
keywords: [advanced query, advanced search, query language, query, filter, search, status, assignee, currentuser, created, updated, order by, project, statuscategory, text, label, serial, former key, startofday, startofmonth]
order: 160
---

**Advanced query** selects tickets, equipment or documents with a query: fields, operators and functions, in
the same form Jira's searches are written, so a query copied from Jira works here.

- On the web: **Tickets**, **Assets** or **Documents** in the side bar → **Advanced query**. The query
  is in the page's address, so a search can be bookmarked or sent to a colleague.
- On the phone: the search icon in Home's search box, or the menu → **Advanced query**.

## Write a query

Clauses `field operator value`, joined by `AND`, `OR`, `NOT` and parentheses, then optionally
`ORDER BY field ASC|DESC, …`:

    assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC, updated DESC
    project in (sparc, eli) AND created >= -7d AND summary ~ "vacuum leak"
    type = "Ion Pump" AND serial ~ VPI AND label = LNFMAC-128463
    status = published AND updated >= startOfMonth() ORDER BY key

| Operator | Means |
|---|---|
| `=` `!=` | equal, not equal (ignoring capital letters) |
| `~` `!~` | contains every word, does not |
| `>` `>=` `<` `<=` | after, before (dates); more, less (numbers) |
| `IN (a, b)` `NOT IN (a, b)` | one of, none of |
| `IS EMPTY` `IS NOT EMPTY` | has no value, has one (`NULL` is the same as `EMPTY`) |

**Values**: a word, a "quoted phrase", a number, a date (`2026-10-01`, `"2026-10-01 14:00"`), a time from now
(`-7d`, `-2w`, `-4h`, `-30m`, `1y`) or a function: `currentUser()`, `now()`, `startOfDay()`, `endOfDay()`,
`startOfWeek()`, `endOfWeek()`, `startOfMonth()`, `endOfMonth()`, `startOfYear()`, `endOfYear()`, each with an
optional offset: `startOfDay(-1)` is yesterday, `startOfMonth("-1M")` last month. A date without a time is
the whole day: `created = 2026-10-01`.

## Fields

| Tickets | |
|---|---|
| `key` (`issuekey`) | the ticket, or the Jira key it came from |
| `summary` (`title`), `description`, `text` | `text ~` looks in title, description and key |
| `status` (`state`), `statusCategory` | `statusCategory = Done` / `!= Done` |
| `priority`, `type` (`issuetype`) | ordered by priority: highest first with `DESC` |
| `assignee`, `reporter`, `watcher` | `currentUser()`, an e-mail, a username or a name |
| `created`, `updated`, `resolved`, `due` | dates |
| `equipment` (`asset`) | its key, a label or serial |
| `labels`, `project` (`workspace`) | |

| Equipment | |
|---|---|
| `key` | the key, or a **former key** |
| `name`, `type`, `category`, `status` | `status`: Active, Provisional, Retired |
| `label`, `labelType` | any label: QR code, barcode, former key, alias; `labelType = qrcode` |
| `serial`, `inventory`, `inventory_number`, `mac`, `asset_tag` | |
| `text` | key, name, labels, serial and every attribute |
| `created`, `updated`, `global`, `project` | |

| Documents | |
|---|---|
| `key` (`code`), `title`, `text` | `text ~` also searches the published text |
| `status` | of the latest revision: draft, in_review, approved, published, retired |
| `published` | the state of the revision people work from |
| `type`, `authority`, `confidentiality`, `owner` | |
| `created`, `updated`, `retired`, `global`, `project` | |

Any **other name** is one of the record's attributes: `voltage_max > 100`, `cf[voltage_max]`,
`"Voltage max"`. A number is compared as a number.

## Which workspaces

Without `project`, a query searches the **current workspace** (and the equipment and documents shared with
every workspace). `project = eli` or `project in (sparc, eli)` searches those, by id or name, among the
workspaces you may read. You see only what you may see: restricted records and fields stay out of the results.
A record of another workspace opens there.

## When a query is refused

The message says what was expected and where: *Expected a value* at the place the value is missing,
*Expected BY* after `ORDER`. History searches (`WAS`, `CHANGED`) and `membersOf()` are not supported.
