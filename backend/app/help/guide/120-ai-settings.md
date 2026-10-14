---
title: AI settings
summary: Connecting an AI endpoint, choosing models, the output-token limit, keeping the knowledge index up to date automatically, and evaluating models for guided entry.
keywords: [ai, ai endpoint, installation, default, inherit, shared, re-ranker, reranker, rerank, llm, model, embedding, vision, speech, transcription, whisper, token limit, output-token limit, reasoning model, qwen, index, knowledge index, automatic, schedule, reindex, evaluation, golden dataset, profile, candidate, activate, troubleshoot]
order: 120
---

The AI features (Describe it, Ask ARGUS, Related by meaning, dictated documents, Tidy with AI, type suggestions,
AI help with imports) use an OpenAI-compatible endpoint chosen per workspace, on the workspace's **AI endpoint**
page. Until it is configured and checked, they are simply not offered.

## Settings for the whole installation

An administrator sets the AI once for every workspace on **Administration → AI**: the same form as below. Every
workspace without settings of its own uses them (the default); its *AI endpoint* page says so. To give one
workspace different settings, press **Give this workspace settings of its own** there; **Use the installation's settings instead** goes back. *Send confidential documents too* is never inherited: each workspace decides it for
itself.

## Connect an endpoint

1. **⚙ Workspace → Administration → AI endpoint**.
2. **Endpoint URL** (for example `https://ai-gateway.example.infn.it/v1`) and the API key, if it needs one. The key
   is stored encrypted and never shown again.
3. **Model** for questions and forms. Optionally:
   - an **Embedding model**, for searching what is written by meaning and for *Related by meaning*;
   - a **Re-ranker model**, to put the passages found in order of how well they answer the question;
   - a **Vision model**, for nameplate photos;
   - a **Speech model** (speech-to-text, a Whisper), for documents dictated in the mobile app; and a text-to-speech
     model.
4. **Output-token limit**: leave it empty and ARGUS sends no limit at all (the model's and the gateway's own limits
   still apply). Set a number only for a gateway that bills or throttles by token: too small a limit leaves a
   reasoning model (Qwen, DeepSeek…) no room to answer.
5. Tick **Offer AI features in this workspace**, save, then press **Check endpoint**: features turn on only once the
   check passes.

Documents marked *riservato* are sent to the model only if you allow it here. Use an endpoint approved for the
information it will receive.

## The re-ranker

With a **Re-ranker model** (for example `bge-reranker-v2-m3`, served at the endpoint's `/rerank`), Ask ARGUS's search
of what is written gathers more passages than it needs and lets the re-ranker order them by relevance to the
question: better passages first, especially for long or loosely worded questions. **Check endpoint** tries it. If it
is unavailable later, the search keeps its own order.

## Written knowledge for Ask ARGUS

Documents (their published text), tickets, comments and the text of attached files are cut into passages and indexed
with the embedding model, so Ask ARGUS and *Related by meaning* can find them by meaning. Under **Written knowledge
for Ask ARGUS** on the same page you see what is indexed, when it last ran and what failed; **Build the index** (later
**Update the index**) runs it now. An update embeds again only what changed.

## Keeping the index up to date by itself

Two settings on the same form, under *Keeping Ask ARGUS's knowledge index up to date*:

- **Index a document as soon as it is published or retired** (on by default): the procedure people just approved is
  what they will ask about next.
- **Refresh the whole index every N hours** (12 by default; **0** turns the timer off): picks up everything else
  with text — tickets and their comments, comments on equipment, attached files, what an import brought in.

Both run the same incremental update as the button; one workspace is indexed at a time. The next scheduled update
is shown under the index. Changing the **embedding model** makes the next update index everything again with the
new model, and the passages of the old one are dropped (they cannot be compared with the new).

## Models for guided entry

**Models for guided entry** lets you try a model before *Describe it* uses it:

1. **Add candidate**: the model's name (and for assets, a vision model).
2. **Evaluate** it on the golden dataset: accuracy per field and per language, whether injected instructions or
   secrets got through, and speed.
3. **Activate** it with a reason, if it passes. **Suspend** goes back to the endpoint's default model.

If every field comes back *missing* with no errors, look at the model's reply in the evaluation's details: an empty
reply, for example a token limit too small for a reasoning model, is a common reason, but not the only one.

When comparing models or settings, use the same questions or dataset and change one thing at a time. Judge accuracy
and evidence, not only fluency and speed.

## When something does not work

| What you see | Check first |
|---|---|
| No AI features at all | *Offer AI features in this workspace* is ticked, and **Check endpoint** passed |
| Questions work, but nothing written is found | an embedding model is set and the index has been built |
| A new document is not found | it is published; the index has run since (or press *Update the index*); you may read it; it is not *riservato* (unless allowed) |
| Empty or cut-short answers | the endpoint's errors on this page, and the output-token limit |
| Photos of nameplates fail | a vision model is set and the endpoint serves it |
| Dictation fails | a speech model is set and the endpoint serves `/audio/transcriptions` |

When reporting a problem, give the workspace, the model, the time, what you did and the message. Never the API key.
