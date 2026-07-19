# The Diátaxis Compass

> Canonical content adapted from https://diataxis.fr/compass/. Snapshot:
> `.firecrawl\diataxis-2026-05-24\pages\diataxis.fr-compass.md`.

The Diátaxis map (see the companion "Map" reference, `map.md` — when present in this skill) is an effective reminder
of the four kinds of documentation and their relationship. But intuition is
not always reliable. When working with documentation, an author is often
faced with the question: _what form of documentation is this?_ or _what form
of documentation is needed here?_ — with no obvious, intuitive answer.

Worse, sometimes intuition provides an immediate answer that is also wrong.

A map is most powerful in unfamiliar territory when we also have a **compass**
to guide us.

## The canonical compass

The compass is a truth-table — a decision-tree — of documentation. It reduces
a more complex, two-dimensional problem to its simpler parts.

| If the content… | …and serves the user's… | …then it must belong to… |
|---|---|---|
| informs action | acquisition of skill | a tutorial |
| informs action | application of skill | a how-to guide |
| informs cognition | application of skill | reference |
| informs cognition | acquisition of skill | explanation |

The compass can be applied equally to **user situations** that need
documentation, or to **documentation itself** that perhaps needs to be moved
or improved. Like many good tools, it's surprisingly banal.

## How to use it

To use the compass, just two questions need to be asked:

1. **Action or cognition?**
2. **Acquisition or application?**

And it yields the answer.

### Flexible terminology

Especially when finding your initial bearings, use the compass's terms
flexibly. Don't get fixated on the exact names:

- **_action_** — practical steps, doing
- **_cognition_** — theoretical or propositional knowledge, thinking
- **_acquisition_** — study
- **_application_** — work

### Four forms of the question

The two questions can be asked from different angles, depending on what you
are trying to figure out:

- _Do I think I am writing for **x or y**?_ (intent check)
- _Is this writing in front of me engaged in **x or y**?_ (audit check)
- _Does the user need **x or y**?_ (need check)
- _Do I want to **x or y**?_ (goal check)

### Two scales of application

Apply the compass at two scales:

- **Close-up**: at the level of a sentence or a word. Is this sentence
  informing action or cognition? Is this paragraph serving a user at study
  or at work?
- **Wide**: at the level of an entire document. Same questions, but applied
  to the whole.

## When the compass is most powerful

The compass is particularly effective when you _think_ you (or the
documentation in front of you) are doing one thing — but you are troubled by
a sense of doubt, or by some difficulty in the work. **The compass forces
you to stop and reconsider.**

Use it when:

- A doc that "felt right" is getting bad reviews.
- A how-to is sprawling into explanation.
- Reference material is starting to feel narrative.
- A tutorial is getting too long because explanation kept creeping in.
- You can't decide whether a new piece of content belongs under
  `tutorials/` or `how-to/`.

## Worked examples

These are illustrative classifications using the compass against typical
artifacts in a documentation wiki.

| Artifact | action/cognition | acquisition/application | Compass verdict |
|---|---|---|---|
| A navigable index of the wiki's pages | cognition (factual structure) | application (someone consults while looking for a topic) | **Reference** (landing) |
| A proposal doc weighing several architectural alternatives | cognition (discussion of options) | acquisition (helps a reader understand why a decision was made) | **Explanation** |
| A typical installation guide | action (do these steps) | application (user already wants to install) | **How-to guide** |
| A first-time setup guide aimed at a brand-new contributor | action (do these steps) | acquisition (learner is new) | **Tutorial** |

When the verdict surprises you, that is a feature of the compass — the
intuition was wrong, the compass corrected it.

## When intuition agrees with the compass

If the compass confirms what intuition already said, treat it as a quick
sanity check and move on. The compass earns its keep when intuition fails.

Source: https://diataxis.fr/compass/
