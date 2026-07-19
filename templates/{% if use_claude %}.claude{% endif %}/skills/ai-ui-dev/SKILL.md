---
name: ai-ui-dom-instrumentation
description: Add lightweight AI-review instrumentation to React/Next.js UI components using data-ai-* attributes, enabled only by flags, so screenshots, selected DOM, and spoken review notes can be mapped back to components, roles, and source files. Trigger this skill when the task mentions AI-assisted UI review, DOM capture, selected element capture, screenshots, data-ai-component, data-ai-source, data-ai-role, or mapping UI evidence to React source code.
---

# AI UI DOM Instrumentation Skill

## Goal

Add lightweight, reversible instrumentation to a React/Next.js codebase so AI tools can correlate captured screenshots, selected DOM elements, and UI review notes with the correct component and source file.

The output should make rendered DOM look like this when AI review mode is enabled:

```html
<button
  data-ai-component="AccountSummaryCard"
  data-ai-source="src/features/accounts/components/AccountSummaryCard.tsx"
  data-ai-role="primary-action"
>
  Ver detalhes
</button>
```

When AI review mode is disabled, the same component must render without these attributes.

---

## Non-negotiable rules

1. Do not change visual design, behavior, routing, data fetching, business rules, or accessibility unless explicitly requested.
2. Do not instrument every DOM node. Instrument only semantically useful UI elements.
3. Do not expose source file paths in normal public production builds.
4. Do not use `Date.now()`, `Math.random()`, `window`, `localStorage`, or browser-only APIs inside the attribute helper used during SSR.
5. Do not introduce hydration mismatch.
6. Do not add runtime listeners, observers, or heavy client-side scripts unless explicitly requested.
7. Prefer a small utility function and explicit component-level usage before proposing Babel/SWC/plugin automation.
8. Keep TypeScript strict and avoid `any` unless there is no better option.
9. Use 2-space indentation.
10. Use lowerCamelCase for variables, parameters, and object fields.
11. Use UpperCamelCase for functions, methods, React components, and classes in this repository.

---

## Preferred implementation strategy

Use a small helper that returns `data-ai-*` attributes only when AI review mode is enabled.

Default behavior by environment:

```txt
local development:
  enabled when NEXT_PUBLIC_ENABLE_AI_REVIEW=true
  may expose data-ai-source

internal staging:
  enabled when NEXT_PUBLIC_ENABLE_AI_REVIEW=true
  may expose data-ai-source if the environment is private

normal production:
  disabled by default

production with temporary review mode:
  prefer data-ai-source-id instead of data-ai-source
```

---

## Step 1 — Add the helper

Create:

```txt
src/lib/ai-review/AiAttrs.ts
```

Recommended implementation:

```ts
export type AiAttrsInput = {
  componentName: string;
  role: string;
  sourcePath?: string;
  sourceId?: string;
  elementName?: string;
};

export type AiDataAttrs = {
  "data-ai-component"?: string;
  "data-ai-role"?: string;
  "data-ai-source"?: string;
  "data-ai-source-id"?: string;
  "data-ai-element"?: string;
};

export function AiAttrs({
  componentName,
  role,
  sourcePath,
  sourceId,
  elementName
}: AiAttrsInput): AiDataAttrs {
  const isAiReviewEnabled =
    process.env.NEXT_PUBLIC_ENABLE_AI_REVIEW === "true";

  const canExposeSourcePath =
    process.env.NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE === "true";

  if (!isAiReviewEnabled) {
    return {};
  }

  const attrs: AiDataAttrs = {
    "data-ai-component": componentName,
    "data-ai-role": role
  };

  if (elementName) {
    attrs["data-ai-element"] = elementName;
  }

  if (canExposeSourcePath && sourcePath) {
    attrs["data-ai-source"] = sourcePath;
    return attrs;
  }

  if (sourceId) {
    attrs["data-ai-source-id"] = sourceId;
  }

  return attrs;
}
```

Why this helper exists:

- It keeps instrumentation centralized.
- It makes disabling instrumentation trivial.
- It avoids repeated environment checks across components.
- It avoids accidental production exposure of source paths.
- It keeps the DOM readable for AI review tools.

---

## Step 2 — Add environment variables

Update `.env.example` or the project’s equivalent environment template:

```env
# Enables data-ai-* attributes for AI-assisted UI review.
NEXT_PUBLIC_ENABLE_AI_REVIEW=false

# Allows rendered DOM to expose source paths such as src/features/.../Component.tsx.
# Keep this false in public production.
NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE=false
```

For local UI review:

```env
NEXT_PUBLIC_ENABLE_AI_REVIEW=true
NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE=true
```

For normal production:

```env
NEXT_PUBLIC_ENABLE_AI_REVIEW=false
NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE=false
```

---

## Step 3 — Instrument only important UI elements

Good targets:

```txt
page roots
main sections
cards
primary and secondary buttons
forms
inputs
selects
filters
tables
table rows with important actions
tabs
menus
modals
drawers
charts
empty states
loading states
error states
navigation blocks
```

Bad targets:

```txt
every div
every span
low-level layout wrappers
purely decorative icons
internal typography wrappers
repeated anonymous containers
```

The goal is not full DOM annotation. The goal is to give AI enough semantic anchors to map evidence back to source code.

---

## Step 4 — Use stable component metadata

For each instrumented component, define a local metadata object near the component.

Example:

```tsx
import { AiAttrs } from "@/lib/ai-review/AiAttrs";

const accountSummaryCardAiSource = {
  componentName: "AccountSummaryCard",
  sourcePath: "src/features/accounts/components/AccountSummaryCard.tsx",
  sourceId: "cmp_account_summary_card"
} as const;

export function AccountSummaryCard() {
  return (
    <Card
      {...AiAttrs({
        ...accountSummaryCardAiSource,
        role: "summary-card"
      })}
    >
      <CardHeader
        {...AiAttrs({
          ...accountSummaryCardAiSource,
          role: "card-header"
        })}
      >
        <CardTitle>Resumo da conta</CardTitle>
      </CardHeader>

      <CardContent
        {...AiAttrs({
          ...accountSummaryCardAiSource,
          role: "card-content"
        })}
      >
        {/* existing content */}
      </CardContent>

      <Button
        {...AiAttrs({
          ...accountSummaryCardAiSource,
          role: "primary-action",
          elementName: "viewDetailsButton"
        })}
      >
        Ver detalhes
      </Button>
    </Card>
  );
}
```

Prefer stable IDs that survive refactors:

```txt
cmp_account_summary_card
cmp_account_table
cmp_inflow_goal_card
cmp_advisor_ranking_table
```

Avoid unstable IDs:

```txt
cmp_1
button_3
wrapper_7
new_component
```

---

## Step 5 — Use a clear role taxonomy

Prefer these roles when possible:

```txt
page-root
section
summary-card
metric-card
card-header
card-content
primary-action
secondary-action
destructive-action
form
form-field
input
select
filter
search
navigation
tabs
tab-trigger
tab-content
table
table-header
table-row
table-cell
row-action
modal
drawer
popover
tooltip
chart
legend
empty-state
loading-state
error-state
permission-state
```

Use project-specific roles when they are more useful, for example:

```txt
advisor-ranking-table
family-account-card
custody-segment-filter
inflow-goal-progress
call-recording-player
```

Avoid vague roles:

```txt
container
wrapper
box
thing
component
misc
```

---

## Step 6 — Optional source map for production-safe mode

If AI review must run in a production-like environment, avoid exposing real source paths in the DOM. Use `data-ai-source-id` and maintain a local source map.

Create:

```txt
src/lib/ai-review/ai-source-map.json
```

Example:

```json
{
  "cmp_account_summary_card": {
    "componentName": "AccountSummaryCard",
    "sourcePath": "src/features/accounts/components/AccountSummaryCard.tsx"
  },
  "cmp_advisor_ranking_table": {
    "componentName": "AdvisorRankingTable",
    "sourcePath": "src/features/ranking/components/AdvisorRankingTable.tsx"
  }
}
```

The captured DOM will show:

```html
<button
  data-ai-component="AccountSummaryCard"
  data-ai-source-id="cmp_account_summary_card"
  data-ai-role="primary-action"
>
  Ver detalhes
</button>
```

Then the AI review package can include the private source map separately.

---

## Step 7 — Avoid hydration mismatch

The helper must be deterministic for server and client rendering.

Safe:

```ts
process.env.NEXT_PUBLIC_ENABLE_AI_REVIEW === "true"
```

Unsafe inside SSR-rendered attributes:

```ts
window.localStorage.getItem("ai-review")
Date.now()
Math.random()
navigator.userAgent
```

If a runtime toggle is required without rebuilding the app, implement it outside SSR-rendered markup, for example through:

```txt
browser extension
DevTools extension
post-hydration debug overlay
local collector script
```

Do not add runtime toggles to the helper unless explicitly requested.

---

## Step 8 — Optional dynamic injection modes

Use these only when explicitly requested.

### Mode A — Source-level conditional injection

This is the default. Add `AiAttrs()` manually to important components.

Pros:

```txt
stable
simple
reviewable
semantic
low risk
works with screenshots and selected DOM
```

Cons:

```txt
requires touching components
not fully automatic
```

### Mode B — Build-time JSX injection

A Babel/SWC plugin can inject attributes into JSX during development or staging.

Use only if the user explicitly wants broad automatic instrumentation.

Pros:

```txt
less manual once configured
can include source file and line metadata
```

Cons:

```txt
can bloat DOM quickly
roles are usually poor or generic
harder to review
riskier with Next.js/SWC configuration
may interfere with compiler assumptions
```

Default decision: do not implement this unless requested.

### Mode C — Runtime DevTools/Fiber inspection

A browser/DevTools extension can inspect selected DOM nodes and infer React component names through development internals.

Use only for local debugging tools, never as app logic.

Pros:

```txt
no source-code changes
useful for one-off exploration
```

Cons:

```txt
relies on unstable internals
not reliable across builds
not suitable for production
source file mapping may be incomplete
```

Default decision: do not implement this inside the application.

---

## Step 9 — Accessibility and privacy rules

Do not use `data-ai-*` attributes as replacements for accessibility.

Still preserve or improve normal semantics when already present:

```txt
aria-label
aria-describedby
button text
form labels
landmarks
heading hierarchy
focus states
```

Never put sensitive data in `data-ai-*` attributes:

```txt
CPF
email
phone number
account number
customer id
token
access key
session id
financial balance
private URL with query params
```

Bad:

```tsx
<div data-ai-customer-id={customer.id}>
```

Good:

```tsx
<div
  {...AiAttrs({
    componentName: "CustomerCard",
    sourcePath: "src/features/customers/components/CustomerCard.tsx",
    sourceId: "cmp_customer_card",
    role: "customer-card"
  })}
>
```

---

## Step 10 — Verification checklist

After implementation, verify:

```txt
[ ] NEXT_PUBLIC_ENABLE_AI_REVIEW=false removes data-ai-* attributes.
[ ] NEXT_PUBLIC_ENABLE_AI_REVIEW=true adds attributes to important components.
[ ] NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE=false does not expose source paths.
[ ] No sensitive business/customer data appears in data-ai-* attributes.
[ ] No visual layout changed.
[ ] No behavior changed.
[ ] No hydration warning appears in the browser console.
[ ] Capturing selected DOM gives enough information to locate the component.
[ ] Instrumentation is sparse enough to be useful instead of noisy.
[ ] Lint/typecheck/build pass.
```

Suggested browser console checks:

```js
document.querySelectorAll("[data-ai-component]").length;
document.querySelectorAll("[data-ai-source]").length;
document.querySelectorAll("[data-ai-source-id]").length;
document.querySelector("[data-ai-role='primary-action']");
```

---

## Step 11 — Agent workflow when applying this skill

When asked to apply this skill to a codebase:

1. Inspect the project structure.
2. Identify whether it uses Next.js App Router, Pages Router, Vite, CRA, or another React setup.
3. Add `src/lib/ai-review/AiAttrs.ts` or the closest equivalent path.
4. Add environment variables to `.env.example` or equivalent config docs.
5. Pick a small set of high-value UI components first.
6. Add `AiAttrs()` to roots and important interactive elements.
7. Prefer semantic roles over generic wrapper labels.
8. Do not refactor UI structure unless required to insert attributes cleanly.
9. Do not alter styling or behavior.
10. Run the project’s lint/typecheck/build commands when available.
11. Report exactly which files were instrumented and how to enable/disable the feature.

---

## Example final response after applying changes

Use this structure when summarizing work:

```md
## Done

Added AI review DOM instrumentation behind environment flags.

## Files changed

- `src/lib/ai-review/AiAttrs.ts`
- `.env.example`
- `src/features/accounts/components/AccountSummaryCard.tsx`
- `src/features/ranking/components/AdvisorRankingTable.tsx`

## How to enable locally

```env
NEXT_PUBLIC_ENABLE_AI_REVIEW=true
NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE=true
```

## How to keep production safe

```env
NEXT_PUBLIC_ENABLE_AI_REVIEW=false
NEXT_PUBLIC_AI_REVIEW_EXPOSE_SOURCE=false
```

## Verification

- AI attributes are disabled by default.
- Source paths are exposed only when explicitly enabled.
- No visual or behavioral changes were made.
```

---

## Optional AGENTS.md snippet

If the repository uses persistent agent instructions, add this short rule to `AGENTS.md`:

```md
## AI UI review instrumentation

When asked to map screenshots, selected DOM, or UI review notes back to React source files, use the `ai-ui-dom-instrumentation` skill. Prefer `AiAttrs()` with environment-gated `data-ai-*` attributes. Do not expose source paths in public production, do not instrument every DOM node, and do not change visual behavior unless explicitly requested.
```
