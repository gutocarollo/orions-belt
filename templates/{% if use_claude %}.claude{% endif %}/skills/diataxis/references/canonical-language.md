# Canonical Language Patterns (4 sets)

> Aggregator of the four "The language of X" sections from diataxis.fr.
> Snapshot:
> `.firecrawl\diataxis-2026-05-24\pages\diataxis.fr-tutorials.md`,
> `…-how-to-guides.md`, `…-reference.md`, `…-explanation.md`.

Each of the four documentation types has a **prescribed voice**. The Diátaxis
site itself lists representative patterns per type. This file collects them
in one place so you can choose the right voice on demand.

Audit usage: if a doc has the wrong voice, that is independent evidence
that its type may be wrong too.

---

## Tutorials

Source: https://diataxis.fr/tutorials/#the-language-of-tutorials

Tutorials mix imperatives, first-person plural, and orientation cues. **Do
not abolish "we" or "let's"** — they coexist with direct imperatives.

| Pattern | Function |
|---|---|
| `We …` | Affirms the tutor–learner relationship: you are not alone; we are in this together. |
| `In this tutorial, we will …` | States what the learner will accomplish. |
| `First, do x. Now, do y. Now that you have done y, do z.` | Imperatives — no room for ambiguity. |
| `We must always do x before we do y because… (see Explanation for details).` | Minimal in-line explanation, link out for depth. |
| `The output should look something like …` | Sets clear expectations. |
| `Notice that … Remember that … Let's check …` | Reflection cues — confirm the learner is on the right track. |
| `You have built a secure, three-layer hylomorphic stasis engine…` | Describes (and mildly admires) what the learner accomplished. |

---

## How-to guides

Source: https://diataxis.fr/how-to-guides/#the-language-of-how-to-guides

How-to guides use direct, conditional imperatives and link out rather than
include comprehensive material.

| Pattern | Function |
|---|---|
| `This guide shows you how to…` | States the problem/task clearly. |
| `If you want x, do y. To achieve w, do z.` | **Conditional imperatives** — the signature how-to construction. |
| `Refer to the x reference guide for a full list of options.` | Link out; do not pollute the practical guide with completeness. |

---

## Reference

Source: https://diataxis.fr/reference/#the-language-of-reference-guides

Reference uses austere, neutral, factual statements. **No opinions, no
instruction, no marketing.**

| Pattern | Function |
|---|---|
| `Django's default logging configuration inherits Python's defaults. It's available as django.utils.log.DEFAULT_LOGGING and defined in django/utils/log.py` | State facts about the machinery and its behaviour. |
| `Sub-commands are: a, b, c, d, e, f.` | List commands, options, operations, features, flags, limitations, error messages, etc. |
| `You must use a. You must not apply b unless c. Never d.` | Provide warnings where appropriate. |

---

## Explanation

Source: https://diataxis.fr/explanation/#the-language-of-explanation

Explanation is discursive. It can offer judgements, weigh alternatives,
unfold internals. It can be mildly opinionated.

| Pattern | Function |
|---|---|
| `The reason for x is because historically, y…` | Explain. |
| `W is better than z, because…` | Offer judgements and even opinions where appropriate. |
| `An x in system y is analogous to a w in system z. However…` | Provide context that helps the reader. |
| `Some users prefer w (because z). This can be a good approach, but…` | Weigh up alternatives. |
| `An x interacts with a y as follows: …` | Unfold the machinery's internal secrets, to help understand why something does what it does. |

---

## Audit shortcut — voice mismatch as a doc-type signal

If a piece of documentation:

- uses "we" and "let's check" → it is reading like a **tutorial** voice. If
  the surrounding doc is meant to be a how-to or reference, that is a smell.
- uses "if you want X, do Y; otherwise see …" → it is reading like a
  **how-to** voice. If used in a tutorial, the tutorial is offering choices
  it shouldn't.
- uses bare lists of values, behaviours, error codes, no "you" → it is
  reading like **reference** voice. If used in explanation, the explanation
  is collapsing into reference.
- uses "the reason for x is", "we chose y because" → it is reading like
  **explanation** voice. If used in reference, the reference is leaking
  narrative.

Voice diagnosis is faster than structural diagnosis. Apply it first.
