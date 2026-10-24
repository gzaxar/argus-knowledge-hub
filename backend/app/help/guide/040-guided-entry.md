---
title: Guided and AI-assisted entry
summary: The checklist beside every form, and Describe it, which fills a form from a sentence, a photo or a file; writing a document by voice or from a photo, and Tidy with AI.
keywords: [checklist, describe it, ai, nameplate, photo, datasheet, pdf, suggestion, form, fill, complete from a file, guided entry, secret, password, redacted, dictate, transcribe, tidy with ai, ocr]
order: 40
---

The forms for a new asset, ticket or document have a side panel with two parts.

## The checklist

Always there, no AI needed. As you type, it shows:

- the steps done so far, and the **Next** question worth answering;
- what is wrong or worth knowing, with a one-click fix where there is one: a key already taken (with a
  link to its record), a serial or inventory number another record holds, a likely duplicate, a
  control-channel name typed as if it were equipment, a missing required attribute;
- for a ticket: when an incident happened, which equipment it affects, similar open tickets;
- for a document: the code it will get, similar titles, the records it mentions.

## Describe it (AI)

Appears when the workspace's AI endpoint is set up (*AI endpoint*).

1. Write what you know, in your own words and any language ("Agilent ion pump VacIon Plus 75, serial
   77120, in the gun area"), or use **Add a photo or file**: a nameplate photo, a PDF datasheet, a Word
   or Excel file, an email.
2. ARGUS shows **suggestions**, each with how sure it is and the words or page it was read from.
3. Press **Use** on the ones you want, or use all of them in empty fields. Nothing you typed is
   overwritten, and nothing is saved until you save the form.

For a ticket, possible causes are shown as *unresolved hypotheses*, never written as findings.

For a **document**, the panel starts from the document itself: paste its text or add its file, then **Rework
with the template** or **Keep it as it is** (see *Documents*). The file is attached to the document, and the
summary the assistant writes goes in the document's **Summary**, never in place of its body.

## What is filtered before the AI sees it

Before text is sent to the model, ARGUS replaces what looks like a secret with *[redacted]*: private keys,
`password=…`, `token=…`, `api_key=…` and similar assignments, *Bearer* tokens, AWS access keys, GitHub
tokens and user names with passwords inside web addresses. A value that looks like a password is never
proposed for a field. The filter recognises these patterns, not every secret: still remove credentials and
unrelated personal information before you paste text or attach a file.

## Check suggestions before using them

Read the words or the page each suggestion was read from. Check identifiers, serial numbers, units and
types. *How sure it is* says how confident the model is; it does not make a value right.

A datasheet describes a model's range; it does not give the serial number or the settings of your unit.
**Use** fills the form; **Save** creates the record. For an existing asset completed from a file, accepting the
proposal in the **Review queue** is what changes the record.

## Complete an existing asset from a file

On an asset's page, **Complete from a file** takes a datasheet, a photo or a note and proposes every value
that differs from the record. The proposals wait in the **Review queue**: nothing on the record changes until
someone accepts them.

## Write a document by voice, or from a photo

In the mobile app, **Ask ARGUS → +** offers two ways to start a document without typing it:

- **Write a document by voice**: record what you would write. The workspace's speech-to-text model turns it
  into text (*AI endpoint → Speech model*); nothing of the recording is kept by the transcription.
- **Write a document from a photo**: photograph a page, a sign or a whiteboard. Its text is read **on the
  phone**; the photo is not sent anywhere to be read.

Either way the editor opens with the text, its first words as the title, and a note saying where it came from:
check the words before you save. The recording or the photo is kept with the new draft as its source.

## Tidy with AI

In the document editor, **Tidy with AI** writes rough text (a dictation, a photographed page, notes) up as a
document: headings, numbered steps, clear wording. It saves nothing: check the result, and **Undo** puts your
own text back.
