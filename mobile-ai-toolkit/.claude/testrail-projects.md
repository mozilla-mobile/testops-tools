# TestRail Project Selection

Every agent that reads or writes TestRail works in **one explicitly chosen
project**. The user chooses it — never the agent, and never a default.

Applies to [`automation-triager`](skills/automation-triager/SKILL.md) and
[`automation-script-writer`](skills/automation-script-writer/SKILL.md).

---

## The prompt

**Before searching for a section or folder, and before retrieving any test
case,** ask the question below and **wait for the answer**. Display it exactly
as written — including the `(*)` and the warning:

```text
Which TestRail project should I use?

1. Firefox for iOS (*)
https://mozilla.testrail.io/index.php?/projects/overview/14

⚠️ IMPORTANT: This is the official TestRail project containing the production
test cases used by the Firefox for iOS team. Exercise extra caution when working
with this project. Any changes to test cases, automation statuses, labels, or
other TestRail data must be intentional and explicitly confirmed by the user
before execution.

Configuration:
  TESTRAIL_iOS_PROJECT_ID (expected value: 14)
  TESTRAIL_iOS_FULL_SUITE_ID (expected value: 45443)

2. [TEMP] iOS test project for TC approvals
https://mozilla.testrail.io/index.php?/projects/overview/92

This is the temporary project used for testing and approvals.

Configuration:
  TESTRAIL_TMP_PROJECT_ID (expected value: 92)
  TESTRAIL_TMP_SUITE_ID (expected value: 107983)
```

The same text is printed by the script, which is the source of truth for the
wording:

```text
python3 scripts/testrail_triage_automation.py projects
```

---

## How the choice reaches the scripts

| Answer | `--project` value | Project id from | Suite id from |
|---|---|---|---|
| 1 — Firefox for iOS (*) | `1` or `firefox-ios` | `TESTRAIL_iOS_PROJECT_ID` | `TESTRAIL_iOS_FULL_SUITE_ID` |
| 2 — [TEMP] TC approvals | `2` or `temp-approvals` | `TESTRAIL_TMP_PROJECT_ID` | `TESTRAIL_TMP_SUITE_ID` |

`--project` is **required** on every `fetch` and `apply`. The ids themselves are
read from `.env` at run time and are never written into a command, a decisions
file or the operational logic. The expected values above are documentation: if
`.env` disagrees the run prints a warning and uses `.env`.

Every run echoes the project it resolved — name, id, suite and the variables
they came from — before it does anything else. Read that banner and confirm it
is the project the user chose.

---

## Rules

1. **Always ask first.** No section lookup, no case read, no metadata call
   before the user has answered. Never silently pick a default, never infer the
   project from the section name, the repo, or a previous run.
2. **Show the warning every time** the choice is presented — the `(*)` and the
   ⚠️ block, in full. Not a summary, not a paraphrase.
3. **Firefox for iOS requires explicit confirmation before any write.** State
   exactly what will change — which cases, which field, which values — get the
   user's confirmation in words, and only then pass `--confirm-firefox-ios`.
   The script refuses the write without it. A read needs no confirmation; a
   `--dry-run` writes nothing and needs none either.
4. **Ids come from `.env`.** Never hardcode `14`, `45443`, `92` or `107983` in
   an operational path. If a required variable is missing or not an integer,
   **stop and explain** — never fall back to the other project.
5. **One project per run.** Use the selected project and suite for every
   subsequent step. Never mix cases, sections, triage results or updates
   between the two projects.
6. **Carry the choice forward.** Name the project in every report and in
   anything handed to another agent, so `automation-script-writer` works in the
   project `automation-triager` triaged. When results arrive without a stated
   project, ask again rather than assuming.
7. **Never print or log the API key**, and never echo credentials when
   reporting which project is in use.
