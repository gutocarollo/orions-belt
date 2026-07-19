# Diátaxis in Complex Hierarchies

> Canonical content adapted from https://diataxis.fr/complex-hierarchies/.
> Snapshot:
> `.firecrawl\diataxis-2026-05-24\pages\diataxis.fr-complex-hierarchies.md`.

The application of Diátaxis to most documentation is fairly straightforward.
The product that defines the domain of concern has clear boundaries, and a
simple arrangement works. But large documentation sets — and especially
those that serve multiple audiences or platforms — quickly outgrow the simple
four-folder layout.

This page is the canonical guidance for that situation — for example, once
a documentation wiki grows into the hundreds of files spanning multiple
subdomains.

## The simple-hierarchy baseline

For a single product with clear boundaries:

```
Home                      <- landing page
    Tutorial              <- landing page
        Part 1
        Part 2
        Part 3
    How-to guides         <- landing page
        Install
        Deploy
        Scale
    Reference             <- landing page
        Command-line tool
        Available endpoints
        API
    Explanation           <- landing page
        Best practice recommendations
        Security overview
        Performance
```

In each case, a landing page contains an overview of the contents within. The
tutorial landing, for example, describes what the tutorial has to offer and
provides context.

## Adding a layer of hierarchy

Even very large documentation sets can use this baseline effectively, though
after a while some grouping within sections becomes wise. Add another layer
of hierarchy — for example, to address different installation flavours
separately:

```
Home                      <- landing page
    Tutorial              <- landing page
        Part 1
        Part 2
        Part 3
    How-to guides         <- landing page
        Install           <- landing page
            Local installation
            Docker
            Virtual machine
            Linux container
        Deploy
        Scale
    Reference             <- landing page
        Command-line tool
        Available endpoints
        API
    Explanation           <- landing page
        Best practice recommendations
        Security overview
        Performance
```

## Contents pages

Contents pages — the home page and any landing pages — provide an overview of
the material they encompass. There is an art to creating a good contents
page. The experience they give users deserves careful consideration.

### The problem of lists

Lists longer than a few items are very hard for humans to read, unless they
have an inherent mechanical order (numerical, alphabetical).

> **Seven items seems to be a comfortable general limit.**

If your tables of contents grow longer than seven, break them up into smaller
groupings.

As always, what matters most is **the experience of the reader**. Diátaxis
works because it fits user needs well — if your execution of Diátaxis leads
to formats that seem uncomfortable or ugly, you need to use it differently.

### Overviews and introductory text

**The content of a landing page itself should read like an overview.**

It should not simply present lists of other content; it should _introduce_
them. _Remember that you are always authoring for a human user, not fulfilling
the demands of a scheme._

Headings and snippets of introductory text catch the eye and provide context.
For example, a **how-to landing page**:

```
How-to guides
=============

Lorem ipsum dolor sit amet, consectetur adipiscing elit.

Installation guides
-------------------

Pellentesque malesuada, ipsum ac mollis pellentesque, risus
nunc ornare odio, et imperdiet dui mi et dui. Phasellus vel
porta turpis. In feugiat ultricies ipsum.

* Local installation       |
* Docker                   |  links to
* Virtual machines         |  the guides
* Linux containers         |

Deployment and scaling
-----------------------

Morbi sed scelerisque ligula. In dictum lacus quis felis
facilisis vulputate. Quisque lacinia condimentum ipsum
laoreet tempus.

* Deploy an instance       |  links to
* Scale your application   |  the guides
```

## Two-dimensional problems

A more difficult problem appears when the structure outlined by Diátaxis
meets **another structure** — often a structure of topic areas, very different
user types, or different deployment contexts.

Examples:

- A product used on **land, sea and air**, used quite differently in each
  case. A user who uses it on land is very unlikely to use it at sea.
- Documentation that addresses the needs of:
  - **users**
  - **developers** who build other products around it
  - **contributors** who help maintain it.
  The same product — but very different concerns.
- A product deployable on different **public clouds**, with each cloud
  presenting different workflows, commands, APIs, GUIs and constraints. Even
  though it is the same product, what users need to know is very different.
  In effect they need documentation for _product-on-cloud-one_,
  _product-on-cloud-two_, and so on.

### Option A — Diátaxis first, then sub-context

```
tutorial
    for users on land
    for users at sea
    for users in the air
[and similarly for how-to guides, reference and explanation]
```

### Option B — sub-context first, then Diátaxis

```
for users on land
    tutorial
    how-to guides
    reference
    explanation
for users at sea
    [tutorial, how-to, reference, explanation sections]
for users in the air
    [tutorial, how-to, reference, explanation sections]
```

Which is better? **Neither is automatically correct.** Both create repetition
and raise questions about sharing material between contexts.

### Where the question actually leads

Firstly, the problem exists with **any** documentation scheme, not just
Diátaxis. Diátaxis helps reveal the problem and demands that it be addressed.

Secondly, the question highlights a common misunderstanding. **Diátaxis is
not a scheme into which documentation must be placed — four boxes.** It
posits four different kinds of documentation, around which documentation
should be structured. This does **not** mean there must be exactly four
divisions of documentation in the hierarchy, one for each category.

## Diátaxis as an approach, not a diagram

Diátaxis can be neatly represented in a diagram — but it is **not the same
as that diagram**.

It should be understood as an _approach_, a way of working with documentation
that identifies four different needs and uses them to author and structure
documentation effectively.

This will _tend_ towards a clear, explicit, structural division into the
four categories — but that is a typical outcome of good practice, not its
end.

## User-first thinking

**Diátaxis is underpinned by attention to user needs**, and once again it is
that concern that must direct us.

What we must document is **the product _as it is for the user_**, the product
as it is in their hands and minds. (Sadly for the creators of products, how
they conceive them is much less relevant.)

Ask:

- Is the product on land, sea and air effectively three different products,
  perhaps for three different users? If so, let that be the starting point.
- If the documentation needs to meet the needs of users, developers and
  contributors, how do _they_ see the product? Does a developer who
  incorporates it into other products typically need a good understanding of
  how it is used? Does a contributor need to know what a developer knows too?
- Perhaps it makes sense to be freer with the structure. In some parts (say,
  the tutorial), developer-facing content might follow on from user-facing
  material, while completely separating the contributors' how-to guides
  from both.

If the structure is not the simple, uncomplicated baseline above, that's
fine — as long as there _is_ arrangement according to Diátaxis principles
and the documentation does not muddle up its different forms and purposes.

## Let documentation be complex if necessary

**Documentation should be as complex as it needs to be.** It will sometimes
have complex structures.

But even complex structures can be made straightforward to navigate as long
as they are logical and incorporate patterns that fit the needs of users.

## Application to a large documentation wiki

Once a wiki grows into the hundreds of files across multiple subdomains —
for example a data-model layer, a pipelines/ingestion layer, page-level
content, and governance rules — the arrangement qualifies as a
**two-dimensional problem** in the canonical sense:

- Dimension 1: Diátaxis type (tutorial / how-to / reference / explanation)
- Dimension 2: subdomain (data model / pipelines / page-level docs /
  governance rules / etc.)

Recommended approach (per canonical guidance):

1. Identify **whose hands and minds** each subdomain serves — analysts,
   data engineers, backend developers, frontend developers, governance team.
   These may overlap but are distinct user-product relationships.
2. Inside each subdomain, structure by Diátaxis type. Resist the urge to
   collapse types — keep the tutorial / how-to / reference / explanation
   separation visible.
3. Use landing pages that **read like overviews**, not bare link lists. An
   index page and a cross-reference page are natural places to start;
   harden them with descriptive intros (one paragraph per subsection, then
   a 5–7 link list).
4. Apply the **7-item rule** to every contents page. If a section has 12
   links, split into two sub-sections, each with its own intro line.
5. Never create empty quadrants. If a subdomain has only reference material
   and no tutorials yet, do not create an empty `tutorials/` folder inside
   it. Let structure form **from the inside out**.

Source: https://diataxis.fr/complex-hierarchies/
