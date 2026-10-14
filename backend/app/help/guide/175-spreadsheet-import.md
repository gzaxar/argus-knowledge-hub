---
title: Importing a spreadsheet
summary: Turning an Excel or CSV list into records — the type found or created (with every default property), where each column goes by rules and the AI, checking every row first, and updating records already imported.
keywords: [spreadsheet, excel, xlsx, csv, import, upload, list, register, inventory, columns, properties, new type, schema, mapping, bulk create, update]
order: 175
---

A list someone keeps in a spreadsheet — an inventory, a register of extinguishers, a list of licences — becomes
records: **each row a record, each column a property**.

Open **Assets → Import a spreadsheet** (also listed on the workspace's **Imports** page).

## 1. The file

An Excel workbook (`.xlsx`) or a CSV file (comma, semicolon or tab separated). The first non-empty row names
the columns; every row below it is a record. A workbook with several sheets asks which one. An old `.xls` must
be saved as `.xlsx` or `.csv` first. At most 20,000 rows at once.

## 2. What the rows become

- **Records of an existing type.** ARGUS ranks the workspace's types by how many of the columns match
  properties of their own, and by how close their name is to the sheet's (or the file's) name. The best one is
  proposed when it clearly fits.
- **A new type**, named by you, **under one of the workspace's types** (Asset for equipment, Record for
  agreements and cases, or any other). Being under it, the new type has every property records of that kind
  have — description, facility, system, lifecycle, criticality, owning service, responsible, and for equipment
  manufacturer, model, serial number, location, inventory number, warranty — besides the columns the sheet
  adds.

With **Use the AI** ticked and an AI endpoint configured, the AI may propose an existing type or a new one and
where it goes. What it proposes is checked: a type or a property it names must exist.

## 3. Where each column goes

Each column goes to the **record's name**, its **key**, a **property** of the type (the defaults included), a
**new property** (with the kind its values suggest: text, number, date, yes/no, a choice list of the values
found), or nowhere. Columns whose names say where they go are placed by rules, which know the usual names in
English and Italian (Nome, Matricola, Produttore, Ubicazione, Stato…); the AI proposes the rest. Each proposal
says who made it (*rule*, *AI*, *you*) and how sure it is. Change any of them.

Values are read as the property expects: numbers in either decimal style (12,5 or 12.5), dates as 2021-02-03
or 03/02/2021, yes/no as yes, no, sì, x, true…, choices by their name. A **location** or another linked record
is found by its key or its name; a **person** by e-mail, username or name; a **group** by name.

## 4. Check every row, then import

**Check every row** reads the whole file and says, row by row, what would happen: **created**, **updated**,
**unchanged**, or why not (a choice not in the list, a number that is not one, a location not found, a required
property empty, a key that belongs to a record of another type). Nothing is written. Rows with a problem are
left out of the import; fix them in the file and check again.

**Import** creates the new type and properties, then the records — as you would by hand, through the ledger, so
each value is your confirmed statement and the history says who imported it. Every record created keeps where
it came from (file, sheet and row) in *Source revision*. The import runs in the background; it is listed on the
**Imports** page with what it created and every row it could not import.

## Updating records later

Map a column to **the record's key**: a row whose key names a record of the type already here **updates** it
(when *Update records whose key is already here* is ticked and you may modify records); a row without a key,
or with a new one, creates a record. Importing the same sheet again changes nothing.

Fields of a restricted class you may not see cannot be written by an import, and are never overwritten by one.
