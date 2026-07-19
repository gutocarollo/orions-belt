# Reference vs Explanation

> Canonical content adapted from https://diataxis.fr/reference-explanation/.
> Snapshot:
> `.firecrawl\diataxis-2026-05-24\pages\diataxis.fr-reference-explanation.md`.

Explanation and reference both belong to the **theory** half of the Diátaxis
map. Neither contains steps to guide the reader; both contain theoretical
knowledge.

The difference between them is — just as in the difference between tutorials
and how-to guides — the difference between the **acquisition** of skill and
knowledge, and its **application**. In other words it is the distinction
between **study** and **work**.

## A straightforward distinction, _mostly_

Most of the time it is fairly easy to recognise whether you are dealing with
reference or explanation. _Reference_, as a form of writing, is well
understood; it is part of distinctions we make about writing from an early age.

Examples are often clearly one or the other. A tidal chart, with its tables
of figures, is clearly reference material. An article that explains _why_
there are tides and how they behave is self-evidently explanation.

## Rules of thumb

The following rules of thumb work in 9 cases out of 10.

- **If it's boring and unmemorable** → probably _reference_.
- **Lists of things** (such as classes or methods or attributes), and
  **tables of information** → generally _reference_.
- **If you can imagine reading it in the bath** → probably _explanation_
  (even if really there is no accounting for what people might read in the
  bath).

Another useful test:

> Imagine asking a friend, while out for a walk or over a drink, **"Can you
> tell me more about <topic>?"** — the answer or discussion that follows is
> most likely going to be an _explanation_ of it.

## …but intuition isn't reliable enough

Mostly we can rely safely on intuition. But only _mostly_ — because it is
also quite easy to slip from one form to the other.

It usually happens while writing reference material that starts to become
expansive. For example, it is perfectly reasonable to include illustrative
examples in reference (just as an encyclopaedia might contain illustrations).
But examples are fun things to develop, and it can be tempting to develop
them into explanation (using them to say _why_, or _what if_, or how it came
to be).

As a result one often finds explanatory material sprinkled into reference.

**This is bad for the reference**, which is interrupted and obscured by
digressions.

**It is also bad for the explanation**, because it is not allowed to develop
appropriately and do its own work.

## The work / study test

The real test, when in doubt about whether something is reference or
explanation, is:

> **Is this something someone would turn to while working** — that is, while
> actually getting something done, executing a task?
>
> **Or is it something they'd need once they have stepped away from the
> work**, and want to think about it?

These two needs reflect how the reader stands in relation to the craft in
question at that moment, in a relationship of **work** or **study**:

- **Reference** is what a user needs to _apply_ knowledge and skill while
  they are working.
- **Explanation** is what someone will turn to to _acquire_ knowledge and
  skill — to **study**.

Understanding these two relationships, and responding to the needs in them,
is the key to creating effective reference and explanation.

## Audit playbook

When auditing a doc you suspect is the wrong type:

1. **Read aloud the first paragraph.** Does it set up _facts to be
   consulted_, or does it set up _a topic to be reflected upon_?
2. **Look at headings.** Reference headings tend to be names of things
   (classes, methods, endpoints, options, commands). Explanation headings
   tend to be questions or topic-phrases ("Why we chose X", "About
   authentication").
3. **Apply the work/study test.** Where would the reader be when they open
   this page?
4. **Look for tables and lists vs prose.** Tables = reference signal.
   Long-form prose with analogies = explanation signal.
5. **Check for opinions.** Reference is **neutral**. Explanation is allowed
   to take perspectives, weigh alternatives, even mildly opinionate.

If a single doc contains both, split it:

- Move the listable, neutral, factual parts into reference.
- Move the discussion, history, comparison, why-we-chose-this parts into
  explanation.
- Cross-link them.

## Common slip — and how to catch it

The most common slip is **reference that grew an explanatory narrative
around an example**. Symptom: an API reference entry that, instead of
documenting the function and stopping, starts to discuss why it exists, how
it evolved, when one might use it versus alternatives, what the broader
architecture implies.

The fix:

1. Cut the narrative out of the reference entry.
2. Move it to an explanation page (titled with implicit "About…").
3. Link from the reference to the explanation: `See [About X →](#)`.

Now the reference is austere again, and the explanation can develop properly.

Source: https://diataxis.fr/reference-explanation/
