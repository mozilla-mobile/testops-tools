# Firefox iOS - TestRail Milestone Automation (Developer Notes)

## Summary

The Firefox iOS TestRail Milestone Automation removes the need for Softvision to manually create milestones and smoke-test runs every time a new iOS release build is generated. Instead, GitHub Actions detect new Bitrise release tags or new RC iterations, automatically generate the correct milestone in TestRail (including handling RC build numbers such as "build 4"), and trigger smoke-test runs. The system also sends release notifications to Slack so QA and Engineering are informed instantly.

This document describes how the automation works end-to-end, how the various GitHub Actions and Python scripts interact, and how to safely test or modify the flow. As an example, we outline the minimal changes required to support RC "build N" milestones, since this is a common type of enhancement that requires touching multiple parts of the system.

### This guide is organized into the following sections:

1. **What the automation does** – A high-level explanation of the purpose and behavior of automation.
2. **How the automation works** – A walkthrough of the full execution chain, including a visual diagram.
3. **How to test & debug changes** – A clear sequence to safely test modifications on a development branch and verify end-to-end behavior.
4. **Minimal required changes (real example)** – A summary of the files that must be modified when extending or fixing the system, demonstrated through the RC "build N" milestone enhancement.

---

## 1. What the automation does

The automation connects **GitHub Actions → Bitrise → TestRail → Slack**.

In summary, this is how automation does that:

- **Checks Bitrise** for new successful iOS release tags.
- **Detects whether**:
  - A new major version was released (e.g., `145.0`), or
  - A new RC build was generated (e.g., `145.3 RC4`).
- **Automatically triggers milestone creation** in TestRail.
- **Creates test runs** for smoke tests.
- **Sends release notifications** to Slack.

The system now supports RC build milestones, e.g.:
- `Build Validation sign-off - Firefox RC 145.3`
- `Build Validation sign-off - Firefox RC 145.3 build 4`

---

## 2. How the automation works (system overview)

### 2.1. Simple explanation

1. A **scheduled GitHub Action** runs every hour and checks Bitrise.
2. If new tags / RC builds are detected, the script triggers another workflow using `gh workflow run`.
3. That workflow invokes a **composite action** which runs the TestRail automation script.
4. The script creates the appropriate milestone in TestRail and sends Slack notifications.

### 2.2. System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions (Scheduled - Every Hour)                        │
│  check_bitrise_for_release.py                                   │
│  - Checks Bitrise for new release tags                          │
│  - Detects new major versions or RC builds                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Triggers (gh workflow run)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Workflow: create-milestone.yml                          │
│  - Receives release-name and release-tag as inputs              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Calls composite action
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Composite Action: firefox-ios-milestone/action.yml             │
│  - Clones the repo                                              │
│  - Sets up Python environment                                   │
│  - Runs testrail_main_ios.py                                    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Executes
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Python Script: testrail_main_ios.py                            │
│  - Creates milestone in TestRail                                │
│  - Creates smoke test runs                                      │
│  - Sends Slack notifications                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. How to test & debug future changes

The system spans multiple workflows, a composite action, and Python scripts. Testing must follow a predictable sequence to avoid accidentally pulling main code.

> **⚠️ Warning:** Even if you manually trigger workflows from your development branch, the composite action or TestRail script will default to `main` unless specific temporary changes are applied.

The steps below ensure you are testing your in-branch code end-to-end.

### Step-by-step testing checklist

1. **Create a feature branch.**
   - All testing should happen from your own branch to avoid impacting production runs.

2. **Update the following files on your branch:**
   - `check_bitrise_for_release.py`: It calls `create-milestone.yml` on the same branch using `gh workflow run --ref <branch>`.
   - `.github/workflows/create-milestone.yml` (point `uses:` to your branch): runs the composite action from the same branch.
   - `.github/actions/firefox-ios-milestone/action.yml`: The composite action clones the repo at the same branch ref and runs the updated `testrail_main_ios.py`.

3. **Run the workflow "Check Bitrise Firefox iOS Tags" manually on your branch via dispatch function in GitHub Actions.**

4. **Verify:**
   - The Bitrise checker triggers `create-milestone.yml` on your branch (`--ref <branch>`).
   - The create-milestone workflow uses the composite action from your branch.
   - The composite action log shows: `git clone --branch <your-branch>`

5. **Remember, once everything works:**
   - Restore the changes. See [PR #186](https://github.com/mozilla-mobile/testops-tools/pull/186) as reference

---

## 4. Minimal Required Changes (example: RC "build N")

Below is a reference example showing how to update all components when adding milestone features such as RC build support.

> **Note:** This example shows exactly which files must be modified to ensure the GitHub Action loads your in-branch code.

### 4.1. `check_bitrise_for_release.py`

**Change:** Ensure the "create milestone" workflow runs on the same branch as the Bitrise checker workflow.

**Modified logic:** Add `--ref $GITHUB_REF_NAME` to `gh workflow run`.

[Line reference](https://github.com/mozilla-mobile/testops-tools/blob/89c38d2c5a5f3769df42a96d770bd03d4a097424/testrail/check_bitrise_for_release.py#L139)

```python
ref = os.environ.get("GITHUB_REF_NAME") or "main"
print(f"Using ref for create-milestone.yml: {ref}")
result = subprocess.run([
    "gh", "workflow", "run", "create-milestone.yml",
    "--ref", ref,
    "-f", f"release-name={release_name}",
    "-f", f"release-tag={tag}"
], capture_output=True, text=True)
```

### 4.2. `.github/workflows/create-milestone.yml`

**Change:** During testing, ensure the workflow uses the composite action from your branch, not from main.

**Modified logic:** Point `uses` to get your branch.

[Line reference](https://github.com/mozilla-mobile/testops-tools/blob/89c38d2c5a5f3769df42a96d770bd03d4a097424/.github/workflows/create-milestone.yml#L18)

```yaml
uses: mozilla-mobile/testops-tools/.github/actions/firefox-ios-milestone@<your-branch>
```

### 4.3. `.github/actions/firefox-ios-milestone/action.yml` (composite action)

**Critical change:** Unless modified, this action always cloned main, so no branch changes were picked up.

**Minimal change summary:** Use your branch as the reference branch.

[Line reference](https://github.com/mozilla-mobile/testops-tools/blob/89c38d2c5a5f3769df42a96d770bd03d4a097424/.github/actions/firefox-ios-milestone/action.yml#L36)

```yaml
echo "Cloning repo ${{ github.repository }} at ref ${{ github.ref_name }}"
git clone --branch "${{ github.ref_name }}" "https://github.com/${{ github.repository }}.git" ../testops-tools
```

This ensures the composite action uses the same branch as the workflow calling it.

### 4.4. `testrail_main_ios.py`

**Change:** Implement the necessary changes. For example, append RC build number (e.g., `build 4`) to the milestone name.

**Minimal change summary:**
- Extract "build N" from `RELEASE_NAME`.
- After calling `build_milestone_name(...)`, append:
  - `build N` (only if N > 1).

**Resulting milestone names:**
- RC1 → `Build Validation sign-off - Firefox RC 145.3`
- RC4 → `Build Validation sign-off - Firefox RC 145.3 build 4`

**Reference:** [PR #186 Commit](https://github.com/mozilla-mobile/testops-tools/pull/186/commits/8b733805ec7189837ca72cabfb24eb92042c53cb)

---

## Additional Resources

- [TestRail API Documentation](https://support.gurock.com/hc/en-us/articles/7077196481428-TestRail-API-v2)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Bitrise API Documentation](https://api-docs.bitrise.io/)
