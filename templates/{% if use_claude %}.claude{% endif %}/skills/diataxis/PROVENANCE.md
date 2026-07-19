# Skill provenance

This skill adapts the Diátaxis framework (https://diataxis.fr/, by Daniele
Procida, CC BY-SA 4.0). Canonical baseline captured on 2026-05-24 via
firecrawl CLI v1.18.0.

## What actually ships in this repo (corrected — see repo-root NOTICE/H5 hardening)

The only Diátaxis-derived material distributed with this framework is
[`references/`](./references/) — 12 curated Markdown files (the pragmatic
distillation this skill's `SKILL.md` describes). **This repo does NOT
contain** `PROVENANCE.json` (a 17-URL/timestamp/SHA-256 index), `INDEX.md`,
or a `pages/` directory with the 17 raw verbatim pages — those artifacts were
part of the private working set of the person who first curated this skill
outside this repo and were never checked in here. Any earlier mention of
those three paths as if they shipped in the kit was inaccurate; treat this
section as the corrected statement. The framework-wide, machine-readable
provenance inventory (this skill included) is `PROVENANCE.json` at the root
of the **harness-wiki framework repository** — not a path reachable from
inside a project this framework was installed into, since that file is
framework tooling and is not part of what `templates/` renders downstream
(intentionally not a clickable relative link here, for that reason: the
correct relative depth differs between this file's location inside the
source repo and its location once rendered into `.claude/skills/diataxis/`
in a target project, and the target never has a `PROVENANCE.json` at all).

## Original snapshot / hash apparatus (historical, not shipped)

The commands below describe how the ORIGINAL curator captured and
hash-verified the 17-page snapshot on their own machine. They are kept here
as a recipe for whoever wants to re-derive a full verbatim snapshot — running
them will NOT reproduce `PROVENANCE.json`/`INDEX.md`/`pages/` inside this
repo unless you also add the code to write those files; nothing here
regenerates artifacts that already exist in this repo.

## Re-capture command

```bash
firecrawl scrape \
  https://diataxis.fr/ \
  https://diataxis.fr/start-here/ \
  https://diataxis.fr/application/ \
  https://diataxis.fr/tutorials/ \
  https://diataxis.fr/how-to-guides/ \
  https://diataxis.fr/reference/ \
  https://diataxis.fr/explanation/ \
  https://diataxis.fr/compass/ \
  https://diataxis.fr/how-to-use-diataxis/ \
  https://diataxis.fr/theory/ \
  https://diataxis.fr/foundations/ \
  https://diataxis.fr/map/ \
  https://diataxis.fr/quality/ \
  https://diataxis.fr/tutorials-how-to/ \
  https://diataxis.fr/reference-explanation/ \
  https://diataxis.fr/complex-hierarchies/ \
  https://diataxis.fr/colophon/ \
  --only-main-content
```

Recompute hashes with `shasum -a 256 pages/*.md` and update `PROVENANCE.json`.

## Hierarchy of truth

When canonical content in `references/` disagrees with the live
https://diataxis.fr/ site, **the live site wins** — there is no local
verbatim snapshot inside this repo to arbitrate against (see the corrected
section above). Pragmatic extensions (templates, examples, checklists,
named patterns) are this skill's own and are signalised as such inline,
typically with a "**Note on provenance**" callout.

## Backup of the pre-2026-05-24 skill

The pre-rewrite state of this skill is **not** preserved inside this repo —
it only ever existed on the original curator's machine (outside version
control at the time) and there is no recoverable path here. If a future
rewrite of this skill is needed, capture the pre-rewrite state in this
repo's own git history first (a real commit), so "restore the previous
version" means `git checkout` against this repo, not a path on someone's
laptop.
