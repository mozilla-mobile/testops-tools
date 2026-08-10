---
name: feature-documenter
description: Connects to TestRail, reads a section named in the request, analyzes every test case inside it, and summarizes them into a short feature document plus a test analysis (redundant tests, missing scenarios, inferred authoring rules). Triggers when the user asks to document, describe, or summarize a feature from its TestRail section.
argument-hint: "[section name or section id, e.g. Pull to refresh or 654483]"
---

## Session Reset & Context Isolation (Run from Scratch)
* **Zero-Context Policy:** Every run is a completely isolated, stateless session.
* **Forget Prior Context:** Do not carry over features, sections, or findings from previous executions or chats.
* **TestRail is the only source:** The documentation describes what the **test cases** assert. Do not import knowledge about the feature from requirements docs, the web, or memory — even if you believe you know the product.
* **No Assumptions:** If the section is not named in the current request, ask. Never guess a section.

# Document a feature from its TestRail section

Reads a TestRail section (and every sub-section under it), analyzes the test
cases, and writes **one short document**: what the feature is and how it works,
plus an analysis of the tests themselves.

This is a **read-only** workflow. It never creates, updates, or deletes anything
in TestRail, and it writes no dump files.

---

## Invocation

```text
/feature-documenter <section name or id>
```

Examples:

```text
/feature-documenter Ad Blocker V1
/feature-documenter 950892
```

---

## Checkpoint (runs inline before spawning the agent)

1. **Parse the argument:** Identify the section/folder name or id. If empty, ask
   the user which TestRail folder to document. Do not guess.
2. **Restate the plan:** Folder requested, the fixed project + suite it will be
   searched in (Step 1), and the target output file
   `work/outputs/<folder name>/feature_documentation.md`.
3. **Spawn `feature-documenter`** to execute the playbook below.

No "go" confirmation is required — the workflow only reads from TestRail and
only writes one file inside `work/outputs/`.

---

## Step 1 — Fetch the cases

Run the read-only fetcher:

```text
python3 scripts/testrail_fetch_section.py "<section>"
```

It **prints the cases to stdout and writes nothing to disk.** Read them from the
command output.

### Fixed search target

The folder name is **always** looked up in:

```text
TESTRAIL_iOS_PROJECT_ID   default 14     — Firefox for iOS
TESTRAIL_FULL_SUITE_ID    default 45443  — Full Functional Tests Suite
```

These are deliberately separate from the importer's `TESTRAIL_PROJECT_ID` /
`TESTRAIL_SUITE_ID`, so documenting a shipped feature never depends on wherever
the last import happened to run. Override per run only if the user explicitly
asks for a different project or suite (`--project-id`, `--suite-id`).

Key behaviours to know:

* A section is resolved by **id**, then exact name, then substring. An ambiguous
  name is an error — re-run with the section id.
* Cases authored as rich text are **flattened to plain text** (HTML list items
  become `-` bullets, entities unescaped). Never re-introduce markup when
  quoting.
* Steps with no expected result print as `(NO EXPECTED RESULT)`. Count them —
  they feed the "Data quality" section.
* If the output is very large, redirect it to a scratch file **outside**
  `work/outputs/` (e.g. under `/tmp/`) and read it from there. Never place a
  dump file in the output folder.
* Credentials come from the same env vars as the importer; a local `.env` is
  loaded automatically. **Never print or log the API key.**

If the script fails, stop and report the error verbatim.

### Sanity-check before analyzing
Confirm the case count matches the header line, and note any case with zero
steps, an empty priority, or expected results that look shifted relative to
their actions. Data problems go in the "Data quality" section — never smooth
them over.

---

## Step 2 — Analyze

Read every case. Build two things: a model of the **feature**, and an assessment
of the **tests**.

For the feature: capabilities from titles; entry states and setup from
preconditions; the interaction model from steps; UI copy, rules, thresholds and
defaults from expected results; functional decomposition from section names;
what matters most from priority.

For the tests, work out:
* **Redundancy** — cases whose coverage is already provided by another case.
  Compare scenarios, not wording.
* **Missing scenarios** — behaviour a production-quality mobile feature would
  need covered that no case touches.
* **Authoring patterns** — the implicit conventions the author followed
  (see Step 3, section 9).

---

## Step 3 — Write the document

Write **one** file: `work/outputs/<folder name>/feature_documentation.md`, where
`<folder name>` is the folder name given as input, preserving its casing and
spacing (e.g. `Ad Blocker V1` → `work/outputs/Ad Blocker V1/`). When the section
was given as a numeric id, use the resolved section name.

**Keep it short.** Target **under ~1,200 words**. This is a briefing, not a
transcript.

Use exactly these sections (omit one only when the cases contain nothing for it,
and say so in a single line):

1. **Feature overview** — what it is and what it does, in 3–6 sentences.
2. **Scope & source** — project, suite, section id, case count, fetch date, and
   one line stating this is reverse-engineered from tests.
3. **Capabilities** — a bulleted list of what a user can do.
4. **How it works** — the interaction model, key rules, states, and thresholds.
   Short prose and bullets. This is the heart of the document.
5. **Accessibility coverage** — **presence only**: whether accessibility tests
   exist (and roughly which kinds, e.g. VoiceOver / Dynamic Type), or that there
   are none. **One or two lines. No details, no per-case breakdown.**
6. **Telemetry coverage** — **presence only**: whether telemetry tests exist, or
   that there are none. **One or two lines. No event names, no payload detail.**
7. **Test coverage profile** — case counts per section, priority distribution,
   and a short paragraph on what the suite emphasizes and what it barely touches.
8. **Test analysis** — two sub-parts:
   * **Redundant tests** — per entry: the case ids, one line on what is
     duplicated, and a suggested action (merge / delete / keep-both-because).
   * **Missing scenarios** — per entry: the scenario, why it matters, and a
     suggested case title. Consider the usual mobile gaps where genuinely
     absent: interruptions, backgrounding, rotation, offline/slow network,
     private browsing, persistence across restart, tablet, first-run and
     upgrade, accessibility, telemetry, localization.
   * These are **suggestions recorded in this file only**. Do **not** modify
     TestRail and do **not** modify any test-case CSV.
9. **Inferred authoring rules** — reverse-engineer how these cases were written
   and state **5–10 concrete rules** the author appears to have followed. Look
   at: granularity (one behaviour per case vs. bundled), step count, how
   preconditions are handled, whether variants are folded into one case as
   "repeat step N in X", naming patterns, priority usage, how expected results
   are phrased, concrete vs. abstract test data. For each rule, say whether it
   **helped or hurt** the suite's value. Frame this section as feedback for the
   `testcase-generator` agent. **Documentation only — change nothing based on
   these rules.**
10. **Data quality & contradictions** — missing expected results, empty
    preconditions, titles that contradict their own steps, copy that differs
    between cases, absent references. Give counts and cite ids.
11. **Open questions** — what the tests do not settle, written as questions for
    the product/engineering owner.

---

## Hard rules

1. **Do not copy the test cases into the document.** No step tables, no
   case-by-case walkthroughs, no reproduced step/expected text. Cite ids
   (`C3167700`) and summarize. This is the most important rule here.
2. **Evidence over invention.** Every factual claim must be traceable to at
   least one case. Cite case ids inline as `C3167700` (or `C3167700, C3167704`).
3. **Mark inference explicitly.** When you connect dots the cases do not state
   outright, prefix it with **(Inferred)** and name the cases the inference
   rests on. Never present inference as documented behaviour.
4. **Quote UI copy verbatim** — but only short strings (labels, messages, error
   text), in quotes, exactly as the expected results write them. Do not
   paraphrase, tidy, or correct them.
5. **Report contradictions, do not resolve them.** If two cases assert different
   copy or behaviour for the same element, document both with their case ids and
   flag it in "Data quality & contradictions".
6. **Never state a requirement the tests do not assert.** If the feature
   obviously *should* do something no case covers, it belongs in "Missing
   scenarios" or "Open questions", not in the behaviour sections.
7. **Suggestions only.** Redundancy and gap findings are recorded in the
   document. Never edit TestRail, a CSV, or any other artifact because of them.
8. **Sections 1–7 describe the feature; sections 8–11 discuss the tests.** Keep
   that separation.
9. **Read-only.** Never create, update, or delete anything in TestRail.
10. **Write exactly one file.** No JSON or Markdown dumps in the output folder.
11. **Never expose credentials** in output, logs, or files.
12. **English, clear and concise**, per `standards.md`.

---

## Output

* `work/outputs/<folder name>/feature_documentation.md` — the only file written.

---

## Report back

State the resolved section (name + id), case and section counts, the output path,
the document's word count, how many claims are inferred rather than directly
asserted, and headline numbers for redundant cases found, missing scenarios
identified, and authoring rules derived.
