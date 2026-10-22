---
title: Ask ARGUS
summary: Asking questions in your own words, checking the answers, following up, letting the assistant propose changes you confirm, and using it on the phone.
keywords: [ask, ask argus, rate, rating, feedback, thumbs up, thumbs down, not useful, wrong answer, chat, voice, speak, microphone, hands-free, read aloud, phone, mobile, assistant, ai, question, answer, conversation, propose, proposal, apply, discard, create with ai, help, how to, register from a photo, dictate, transcribe, document from a photo]
order: 110
---

**Ask ARGUS** answers questions in your own words, in any language, from the workspace's equipment, tickets,
documents, the text of attached files and this guide.

## Ask

1. Open **Ask ARGUS** and ask: "Which ion pumps are on the linac?", "What went wrong with the gun vacuum
   before, and how was it fixed?", "How do I export a workspace?".
2. You see the **lookups** as it works (*Searching equipment*, *Reading what is written*, *Opening a record*).
   Each record key in the answer opens its record.
3. **Follow up** in the same conversation ("which of those are in AC1?"): earlier turns are its context.
   **New chat** starts afresh. Conversations are kept, for you only.

An answer built from no lookups is marked as such: do not treat it as coming from the workspace's records.
When something is not found, it says what it looked at.

## Check an answer

Open the linked records and check that they say what the answer says, about the right equipment, at the right
revision or date. Lookups do not make every conclusion correct.

*Not found* can mean the information is not there, that you may not read it, or that it has not been indexed
yet. In a follow-up, give asset keys, dates and the part of the machine.

## Rate an answer

Under each answer, **👍** says it was useful; **👎** asks, optionally, what was wrong or missing. Each answer is
rated once. The rating is kept **without your name**: the question, the answer, the workspace, the model, the
ARGUS version, the client and the lookups it made (not what they returned). An answer rated not useful becomes
an **Argus Knowledge** ticket for the people who improve Ask ARGUS (the *ARGUS Knowledge feedback* workspace,
seen only by them and administrators).

In the comment, say what is wrong, the records that show it and what it should have said. Leave out secrets and
unrelated personal information.

## Let it make changes for you

Ask it to create, change or relate records: "Create screen station SCN01, composed of camera … and motor …". It
**proposes**; it never changes anything by itself.

1. It looks up the records and checks its proposals: the type exists, the records exist, the attributes belong
   to the type, the relations are allowed. New records it proposes are called `new:1`, `new:2`… so they can be
   related in the same answer.
2. **Proposed changes** appears under the answer, with a box for each.
3. **Apply** all of them or the ones ticked, or **Discard**. Applying goes through the same checks as the forms,
   your rights, and your name in the history.
4. Each then shows **applied** (with a link to the record), **failed** (with the reason) or **discarded**. A
   relation that needs a record whose creation failed fails too.

You are only offered what your rights allow you to do by hand.

## If only some changes succeed

Read each result and open what was created or changed. Correct the ones that failed and retry only those: do
not create again what already succeeded. When you apply a subset, include the creations the selected relations
need.

## Ask it how to do something

"How do I import an EPIK8s configuration?", "step by step, how do I move local workspaces to production?": it
answers from this guide, one step at a time if you like. The **Ask ARGUS to walk me through this** links in Help
start the same.

## On the phone (ARGUS Field)

**Ask** is a tab of its own in the mobile app.

1. Type a question, or press the **microphone** and say it: when you pause, what was heard is sent as the
   question.
2. You see the lookups while it works. Answers are formatted (lists, bold, tables), and the record keys they
   cite open the record. Follow-ups continue the conversation; **New conversation** starts afresh; **Earlier
   conversations** reopens past ones, the web's included.
3. The **speaker** under an answer reads it aloud; **👍 / 👎** rate it (see *Rate an answer*).
4. **Hands-free** (the headset icon): each answer is read aloud, then the app listens for the next question. It
   stops when you say nothing, or when you press the headset again.

Spoken questions are turned into words by the phone's speech-recognition service (on Android usually Google's,
on iOS Apple's), which may process the audio under its own terms; only the recognised words go to ARGUS.
Answers are read aloud by the phone. The first time, the phone asks to allow the microphone. Check equipment
codes in what was heard before relying on the answer.

## More than questions, on the phone

The **+** beside the question box offers:

- **Register equipment from a photo**: the camera opens on the nameplate, the form is filled from it, and you
  check and register (see *The mobile app (ARGUS Field)*).
- **Find or register by its label**: scan a QR code or barcode, read a printed serial, or type it; if nothing
  carries it, register a new unit.
- **Write a document by voice**: record it; the workspace's speech-to-text model transcribes it; you check the
  text in the editor; the recording is kept with the draft.
- **Write a document from a photo**: photograph a page; its text is read on the phone; the photo is kept with
  the draft.

## When it is unavailable

Ask needs the workspace's AI endpoint to be set up and checked; searching what is written by meaning also needs
the knowledge index. Writing a document by voice needs a speech model. See *AI settings*.
