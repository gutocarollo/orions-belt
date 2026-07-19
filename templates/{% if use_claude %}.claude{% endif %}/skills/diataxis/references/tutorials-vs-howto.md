# Tutorial vs How-to Guide — the most common conflation

> Canonical content adapted from https://diataxis.fr/tutorials-how-to/.
> Snapshot:
> `.firecrawl\diataxis-2026-05-24\pages\diataxis.fr-tutorials-how-to.md`.

In Diátaxis, tutorials and how-to guides are strongly distinguished. It is a
distinction that is often not made. **The single most common conflation made
in software product documentation is between the tutorial and the how-to
guide.**

This page is the canonical argument for the distinction and an aid for
deciding which side an existing artifact belongs to.

## What they have in common

In important respects, tutorials and how-to guides are similar:

- Both are **practical guides** — they contain directions for the user to
  follow.
- Neither exists to explain or convey information.
- Both exist to guide the user in what to _do_ rather than what to _know_.
- Both set out **steps for the reader to follow**, both promise that following
  those steps leads to a successful conclusion.
- Neither makes much sense except for a user who has their hands on the
  machinery, ready to do things.
- Both describe **ordered sequences of actions**.

They are closely related — and, like many close relations, can be mistaken
for one another at first glance.

## What matters is what the user needs

Diátaxis insists that what matters in documentation is the needs of the user.
It is by paying attention to need that we correctly distinguish tutorials
from how-to guides.

Sometimes the user is **at study**, and sometimes the user is **at work**.
Documentation has to serve both those needs.

- A **tutorial** serves the user who is at study. Its obligation is
  _to provide a successful learning experience_.
- A **how-to guide** serves the user who is at work. Its obligation is
  _to help the user accomplish a task_.

These are completely different needs and obligations. They are why the
distinction matters: **tutorials are learning-oriented; how-to guides are
task-oriented.**

## At study and at work — the medical analogy

The canonical illustration uses a doctor.

### At study — learning to suture

Early in your training, you learn how to suture a wound. You start in the lab
with your fellow students, at benches with small skin pads in front of you
(synthetic blocks that mimic skin, fat and muscle). You are provided with
exactly what you need — gloves, scalpel, needle, thread — and step-by-step
you are shown what to do, and what will happen when you do it.

Then it is your turn. You pick up the scalpel and tentatively draw it across
the top of the pad, and make an ineffectual incision. Your neighbour looks
dismayed at their own ragged, uneven cut. After a few attempts, with feedback
from the tutor, you make a cleaner cut.

Now you are asked to stitch it back up. You watch the tutor close the wound
in the pad with neat, even stitches. You fumble with the thread, hold things
in the wrong hand, drop the needle, fail to maintain sterility. Eventually
you stitch the wound — badly. Your final result is an ugly scene of stretched
skin and crude stitches. The teaching assistants are critical even of the
parts you thought were right.

But — **you have stitched your first wound**. You will come back to this
lesson again and again, and bit by bit your fumbling will turn into confident
practice. You will have acquired basic competence. You will have **learned
by doing**.

This is a tutorial. A _lesson_, safely in the hands of an instructor who
looks after the interests of the pupil.

### At work — performing an appendectomy

Now consider the doctor at work. As a doctor at work, you are already
competent. You have refined clinical skills such as suturing, and you can
apply them on a daily basis in real-world situations.

Consider a standard appendectomy. A clinical manual lists the equipment and
personnel required in the theatre. It shows how to station the team and lay
out tools, stands and monitors. It proceeds step-by-step through the actions
the team must follow, ending with the formal handover to the post-operative
team.

The manual shows what incisions need to be made where, but they depend on
whether you are performing an open or laparoscopic procedure, whether
pre-operative imaging is available, and so on. It includes special steps for
infants or for converting to an open procedure mid-operation. **Many of the
steps are of the form _if this, then that_.**

Having a manual helps ensure all the steps are done in the right order and
none are omitted. As a team, you check key steps; sometimes you refer to the
manual during the procedure itself.

Even for routine surgical operations, clinical manuals contain lists of
steps and checks. **These manuals are how-to guides.** They are not there
to teach you — you already have your skills. They are there to guide you
safely in your clinical practice to accomplish a particular task. **They
serve your work.**

## The canonical 15-point contrast

| Aspect | Tutorial | How-to guide |
|---|---|---|
| 1. Purpose | help pupil acquire basic competence | help already-competent user perform a particular task correctly |
| 2. What it gives | a learning experience — what the learner does and experiences | direction for the user's work |
| 3. Path | carefully-managed path, starting → conclusion, with required encounters | aims for a successful result; the path cannot be managed — real world disrupts |
| 4. Familiarity | familiarises learner with tools, language, processes, responses | assumes familiarity |
| 5. Setting | contrived learning environment, set up for success | real world, takes what it throws |
| 6. The unexpected | eliminates the unexpected | prepares for the unexpected, alerts user |
| 7. Branching | single line, no choices/alternatives | forks and branches: _If this, then that. In the case of …, an alternative approach is to…_ |
| 8. Safety | must be safe; always possible to restart | cannot promise safety; often only one chance |
| 9. Responsibility | teacher's responsibility — teacher solves trouble | user's responsibility — user gets into and out of trouble |
| 10. Questions | learner may not even have competence to ask the right questions | user is assumed to be asking the right questions |
| 11. Bodily/basic | explicit about basic things — where to type, how to manipulate, how long to wait | relies on this as implicit, even bodily knowledge |
| 12. Examples | concrete and particular — specific known tools, materials, processes | general approach; specifics will vary case-to-case |
| 13. What it teaches | general skills and principles applicable to many cases later | nothing — user is completing a particular task |
| 14. User stance | at study | at work |
| 15. Orientation | learning-oriented | task-oriented |

None of these distinctions are arbitrary. They all emerge from the
distinction between **study** and **work**, which is the key to understanding
what the user of documentation needs.

## The "basic vs advanced" false distinction

A common but understandable conflation is to see the difference between
tutorials and how-to guides as the difference between **the basic** and
**the advanced**.

After all — tutorials are for learners, how-to guides for already-skilled
practitioners. Tutorials must cover the basics, how-to guides handle
complexities that learners should not face.

**But there is more to the story.**

A clinical procedure manual could be a manual for a basic routine procedure
of very low complexity. It could describe steps for mundane matters such as
correct completion of paperwork or disposal of particular materials.
**How-to guides can, do and often should cover basic procedures.**

At the same time, even as a qualified doctor, you will find yourself back in
training situations. Some of them may be very advanced and specialised,
requiring a high level of skill already.

A senior anaesthetist might attend a course "Difficult neonatal intubations".
The practical part of the course is a learning experience — a lesson, safely
in the hands of instructors — just as it was when years earlier they were
learning to suture their first wound. The complexity is wholly different,
and so is the baseline of skills required to participate. But the form is
the same, and serves the same kind of need.

The same applies to software documentation: a tutorial can present something
complex or advanced. A how-to guide can cover something basic or well-known.
**The difference between the two lies in the need it serves: the user's
study, or their work.**

## Safety and success — why getting this wrong harms users and the product

A clinical manual that conflated education with practice — that tried to
teach while at the same time providing a guide to a real-world procedure —
would be a **literally deadly document**. It would kill people.

In software documentation, we get away with much more, because our
conflations rarely kill anyone. But we cause a great deal of low-level
inconvenience and unhappiness to our users — and we add to it every time we
publish a tutorial or how-to guide that does not understand whether its
purpose is to help the user **study** or **work**.

We hurt ourselves too. **Users do not have to use our product.** If our
documentation does not bring them to success — does not meet their needs at
their current stage in the cycle of interaction — they will find something
else that does, if they can.

The conflation of tutorials and how-to guides is not the only one made
between different kinds of documentation, but it is one of the easiest to
make. And it is a particularly harmful one, because it risks getting in the
way of newcomers — the users we most want to convert into committed ones.

## How to use this distinction in audits

When you suspect a doc conflates tutorial and how-to:

1. Read the title. Does it start with "How to …"? That signals a how-to, but
   does not confirm it.
2. Identify the **user state**: is the reader meant to be _at study_ or _at
   work_ when they reach this page?
3. Count **forks** in the body. A tutorial should have none. A how-to may
   have many.
4. Look for **explanatory digressions**. Tutorials should minimise them. A
   how-to that explains why it works is drifting toward tutorial OR drifting
   toward explanation.
5. Look for **safety / responsibility framing**. Tutorial language: "Don't
   worry if you make a mistake — you can restart." How-to language: "Back up
   before you begin."
6. Apply the **15-point contrast** table above. Where the doc lands on each
   axis is the verdict.

If you find a single doc straddles the two, **split it** into a clearly
labeled tutorial and a separately labeled how-to. Cross-link them.

Source: https://diataxis.fr/tutorials-how-to/
