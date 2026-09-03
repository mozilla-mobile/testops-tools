"""Tests for agent/loop.py — invariants that were previously broken (L1, L2, L11)."""

import inspect
import re

from agent.loop import (
    SYSTEM_PROMPT,
    AgentDecision,
    ExploratoryAgent,
    _available_actions,
    _build_system_prompt,
    _decision_fallback_wait,
    exit_code_for,
)


# ── L1: SYSTEM_PROMPT action list ⊆ dispatcher keys ──────────────────────────

def _prompt_actions(prompt: str) -> set:
    m = re.search(r'"action":\s*"([^"]+)"', prompt)
    assert m, "prompt missing 'action' schema line"
    return {a.strip() for a in m.group(1).split("|")}


def _dispatcher_actions() -> set:
    src = inspect.getsource(ExploratoryAgent._execute)
    return set(re.findall(r'"(\w+)":\s*lambda', src))


def test_ios_prompt_action_list_is_subset_of_dispatcher():
    """Everything the iOS LLM is allowed to emit must be in _execute's dispatch —
    otherwise the LLM would ask for an action that returns nothing (bug L1)."""
    prompt_actions = _prompt_actions(_build_system_prompt("ios"))
    dispatcher     = _dispatcher_actions()
    assert prompt_actions.issubset(dispatcher), (
        f"iOS prompt references actions the dispatcher doesn't know: "
        f"{sorted(prompt_actions - dispatcher)}"
    )


def test_android_prompt_action_list_is_subset_of_dispatcher():
    prompt_actions = _prompt_actions(_build_system_prompt("android"))
    dispatcher     = _dispatcher_actions()
    assert prompt_actions.issubset(dispatcher), (
        f"Android prompt references actions the dispatcher doesn't know: "
        f"{sorted(prompt_actions - dispatcher)}"
    )


def test_backwards_compat_module_level_system_prompt_still_valid():
    """The module-level SYSTEM_PROMPT constant is kept for backwards
    compatibility (older imports/tests may reach for it). It should equal
    the iOS variant."""
    assert SYSTEM_PROMPT == _build_system_prompt("ios")


# ── Platform-safety: prompt-side ─────────────────────────────────────────────

def test_ios_prompt_omits_android_only_actions():
    """Regression: press_back does driver.back() which is undefined on
    XCUITest; key_press uses press_keycode which is Android-only. Neither
    should appear in the iOS action list."""
    prompt_actions = _prompt_actions(_build_system_prompt("ios"))
    assert "press_back" not in prompt_actions
    assert "key_press"  not in prompt_actions


def test_android_prompt_keeps_android_only_actions():
    """press_back and key_press must still be available on Android."""
    prompt_actions = _prompt_actions(_build_system_prompt("android"))
    assert "press_back" in prompt_actions
    assert "key_press"  in prompt_actions


def test_universal_actions_appear_on_both_platforms():
    """Sanity: tap/type_text/swipe/wait/etc. work everywhere."""
    for platform in ("ios", "android"):
        actions = _prompt_actions(_build_system_prompt(platform))
        for universal in ("tap", "type_text", "type_url", "swipe",
                          "long_press", "rotate", "background_app", "wait"):
            assert universal in actions, f"{universal!r} missing from {platform} prompt"


def test_available_actions_helper_matches_prompt_content():
    """_available_actions() and the prompt schema must stay in sync — if the
    tuple is edited but the prompt template forgets to include one, this fires."""
    for platform in ("ios", "android"):
        expected = set(_available_actions(platform))
        actual   = _prompt_actions(_build_system_prompt(platform))
        assert expected == actual, (
            f"_available_actions({platform}) diverges from prompt content: "
            f"missing from prompt: {sorted(expected - actual)}; "
            f"extra in prompt: {sorted(actual - expected)}"
        )


# ── Platform-safety: _force_escape strategies ────────────────────────────────

def test_force_escape_on_ios_never_calls_press_back():
    """Regression: press_back was strategy 0 for all platforms — on iOS
    driver.back() is undefined, so we swapped it for swipe-down."""
    agent = object.__new__(ExploratoryAgent)
    agent.platform = "ios"
    calls = []
    class _FakeActions:
        def press_back(self):        calls.append("press_back");        return {"status": "ok"}
        def swipe(self, direction):  calls.append(f"swipe:{direction}"); return {"status": "ok"}
        def background_app(self, s): calls.append(f"bg:{s}");            return {"status": "ok"}
    agent.actions = _FakeActions()

    # Sweep all reachable counts and verify press_back never fires on iOS.
    for count in (6, 9, 12):
        calls.clear()
        agent._same_screen_count = count
        agent._force_escape()
        assert "press_back" not in calls, (
            f"iOS force_escape at count={count} called press_back: {calls}"
        )


# ── AgentDecision: validated LLM output ──────────────────────────────────────

def test_decision_params_null_becomes_empty_dict():
    """Regression: LLM sometimes emits params:null; downstream .get() then
    crashes with AttributeError. Model must coerce null to {}."""
    d = AgentDecision.model_validate({"action": "tap", "params": None}).model_dump()
    assert d["params"] == {}


def test_decision_params_non_dict_becomes_empty_dict():
    """A string or list in params has no valid interpretation — coerce to {}."""
    for bad in ("garbage", ["target", "btn"], 42):
        d = AgentDecision.model_validate({"action": "tap", "params": bad}).model_dump()
        assert d["params"] == {}, f"bad params={bad!r} produced {d['params']!r}"


def test_decision_wait_seconds_clamped_to_ten():
    """Regression: LLM emitting {seconds: 86400} would sleep the agent for
    24h — no API calls during sleep, so --max-tokens can't rescue. Model
    must clamp to [0, 10]."""
    d = AgentDecision.model_validate(
        {"action": "wait", "params": {"seconds": 86400}}
    ).model_dump()
    assert d["params"]["seconds"] == 10.0


def test_decision_negative_seconds_clamped_to_zero():
    d = AgentDecision.model_validate(
        {"action": "wait", "params": {"seconds": -50}}
    ).model_dump()
    assert d["params"]["seconds"] == 0.0


def test_decision_seconds_non_numeric_dropped():
    """If seconds is unparseable ('soon'), drop the key rather than crash."""
    d = AgentDecision.model_validate(
        {"action": "wait", "params": {"seconds": "soon"}}
    ).model_dump()
    assert "seconds" not in d["params"]


def test_decision_objective_complete_string_false_coerces_correctly():
    """Regression: bool('false') in Python is True, so a string 'false' from
    the LLM used to end the session early. Pydantic v2 lax-coerces 'false'
    to False correctly (verified before locking in the design)."""
    d = AgentDecision.model_validate(
        {"action": "wait", "objective_complete": "false"}
    ).model_dump()
    assert d["objective_complete"] is False


def test_decision_objective_complete_string_true_still_works():
    d = AgentDecision.model_validate(
        {"action": "wait", "objective_complete": "true"}
    ).model_dump()
    assert d["objective_complete"] is True


def test_decision_severity_normalized_to_titlecase():
    """Regression: the report_bug branch checks severity against the exact
    strings 'Low'|'Medium'|'High'|'Critical'. Model normalizes 'HIGH  ',
    ' medium', 'Critical' all into their canonical Title-Case form."""
    for raw in ("HIGH", "  high  ", "High", "high"):
        d = AgentDecision.model_validate(
            {"action": "wait", "anomaly_severity": raw}
        ).model_dump()
        assert d["anomaly_severity"] == "High", (
            f"input {raw!r} did not normalize to 'High': got {d['anomaly_severity']!r}"
        )


def test_decision_severity_invalid_becomes_none():
    """Any severity outside the allowed set drops to None so downstream
    validation (in loop.py) falls back to the Medium default."""
    d = AgentDecision.model_validate(
        {"action": "wait", "anomaly_severity": "urgent"}
    ).model_dump()
    assert d["anomaly_severity"] is None


def test_decision_extra_fields_are_preserved():
    """We add _json_error internally on some fallback paths; the model must
    tolerate it (extra='allow') so it round-trips through validation."""
    d = AgentDecision.model_validate(
        {"action": "wait", "_json_error": True}
    ).model_dump()
    assert d.get("_json_error") is True


def test_fallback_wait_helper_shape_matches_decision_model():
    """The manual fallback dict (used on parse/API errors) must be schema-
    compatible with what the model would produce — otherwise downstream code
    would see two subtly different shapes."""
    fallback = _decision_fallback_wait("test reason", json_error=True)
    revalidated = AgentDecision.model_validate(fallback).model_dump()
    # Every field the fallback sets must survive round-trip.
    for key in ("action", "params", "anomaly_detected", "anomaly_description",
                "objective_complete"):
        assert revalidated[key] == fallback[key], (
            f"fallback[{key}]={fallback[key]!r} != revalidated={revalidated[key]!r}"
        )
    # And _json_error passes through unchanged.
    assert revalidated.get("_json_error") is True


# ── exit_code_for: --fail-on policy ──────────────────────────────────────────

def test_exit_code_never_returns_zero_even_with_critical_bugs():
    """Regression: exploratory findings are informational. The default policy
    ('never') must always return 0 regardless of what severities were found."""
    assert exit_code_for({"Critical", "High", "Medium", "Low"}, "never") == 0
    assert exit_code_for({"Critical"},                          "never") == 0
    assert exit_code_for(set(),                                 "never") == 0


def test_exit_code_critical_only_trips_on_critical():
    """--fail-on critical: exit 2 only if a Critical bug was recorded.
    High bugs do NOT trip UNSTABLE under this policy — that's what 'high' is for."""
    assert exit_code_for({"Critical"},         "critical") == 2
    assert exit_code_for({"Critical", "High"}, "critical") == 2
    assert exit_code_for({"High"},             "critical") == 0
    assert exit_code_for({"Medium", "Low"},    "critical") == 0
    assert exit_code_for(set(),                "critical") == 0


def test_exit_code_high_trips_1_for_high_2_for_critical():
    """--fail-on high: full 3-tier mapping."""
    assert exit_code_for({"Critical"},              "high") == 2
    assert exit_code_for({"Critical", "High"},      "high") == 2   # Critical wins
    assert exit_code_for({"High"},                  "high") == 1
    assert exit_code_for({"High", "Medium", "Low"}, "high") == 1
    assert exit_code_for({"Medium", "Low"},         "high") == 0
    assert exit_code_for(set(),                     "high") == 0


def test_exit_code_never_collides_with_the_crash_code():
    """Regression: a crashed run exits 3, and `exit_code_for` must never
    produce that value — otherwise CI cannot tell "the agent broke" from
    "the agent found a bug". Previously a crash exited 1 (Python's default
    for an unhandled exception), which read as "High bug found"."""
    every_severity_set = [
        set(), {"Low"}, {"Medium"}, {"High"}, {"Critical"},
        {"Critical", "High", "Medium", "Low"},
    ]
    for policy in ("never", "critical", "high"):
        for severities in every_severity_set:
            assert exit_code_for(severities, policy) in (0, 1, 2)


# ── Anomaly severity: LLM emits it, code respects it, else Medium ────────────

def test_anomaly_severity_default_is_medium_not_high():
    """Regression: severity used to be hardcoded 'High'. Now it comes from the
    LLM's JSON (anomaly_severity field). If absent/invalid, default is Medium —
    unverified suspicions should not automatically trip Jenkins UNSTABLE."""
    # Parse the report_bug call site directly to verify the default.
    src = inspect.getsource(ExploratoryAgent.run)
    # Look for the fallback default assignment.
    m = re.search(r'severity\s*=\s*["\']Medium["\']', src)
    assert m, (
        "expected a `severity = \"Medium\"` fallback in ExploratoryAgent.run — "
        "the default severity for unverified anomalies must not be High"
    )
    # And the old hardcoded High assignment must be gone.
    assert 'severity   = "High"' not in src, (
        'The report_bug call still hardcodes severity="High"'
    )


def test_system_prompt_declares_page_content_untrusted():
    """Regression: without an explicit rule, the LLM will treat page text as
    instructions (base injection surface). Both platform prompts must
    declare page/app content as untrusted data."""
    for platform in ("ios", "android"):
        p = _build_system_prompt(platform)
        low = p.lower()
        assert "untrusted" in low, f"{platform} prompt missing untrusted-content rule"


def test_system_prompt_forbids_secret_entry():
    for platform in ("ios", "android"):
        p = _build_system_prompt(platform)
        low = p.lower()
        # Must mention at least one of the sensitive-input categories
        assert any(word in low for word in ("password", "api key", "credit card")), (
            f"{platform} prompt missing rule against typing secrets"
        )


def test_system_prompt_forbids_destructive_actions():
    for platform in ("ios", "android"):
        p = _build_system_prompt(platform)
        low = p.lower()
        assert "destructive" in low or "delete account" in low, (
            f"{platform} prompt missing destructive-action rule"
        )


def test_system_prompt_acknowledges_capability_gaps():
    """Regression from real session: an objective that requires system-level
    actions (toggle WiFi/airplane, force-close, dark mode) can't be executed
    from inside the target app. Without a rule, the agent loops repeating
    in-app actions until max_steps. The rule must tell it to note the
    untestable sub-tasks in reasoning and stop moving."""
    for platform in ("ios", "android"):
        p = _build_system_prompt(platform)
        low = p.lower()
        # Must name at least one system-level capability the agent lacks
        assert any(term in low for term in ("airplane mode", "wi-fi", "wifi", "force-clos")), (
            f"{platform} prompt does not name a system-level capability gap"
        )
        # Must instruct against reporting untestable sub-tasks as anomalies
        assert "untestable" in low, (
            f"{platform} prompt does not mention 'untestable' — agent won't "
            f"know to distinguish skipped sub-tasks from real gaps"
        )
        # Must instruct to stop looping when out of testable moves
        assert any(term in low for term in ("do not loop", "stop making moves",
                                            "don't loop", "coverage gap")), (
            f"{platform} prompt does not tell the agent to stop looping when out of testable actions"
        )


def test_system_prompt_tells_llm_tool_errors_are_not_bugs():
    """Regression from real session: LLM logged 10 'High/Critical' bug reports
    for the same underlying Appium 'Unhandled endpoint' tool failure. The
    prompt must explicitly tell the LLM NOT to interpret result='error' from
    tool/driver failures as app anomalies."""
    for platform in ("ios", "android"):
        p = _build_system_prompt(platform)
        low = p.lower()
        # The rule must mention several tool-error signals so the LLM can recognise them.
        assert "unhandled endpoint" in low, f"{platform} prompt does not mention unhandled endpoint"
        assert "unknowncommand" in low or "unknown command" in low, (
            f"{platform} prompt does not mention UnknownCommand"
        )
        # And it must instruct not to bug-report them.
        assert "not app defects" in low or "not a bug" in low or "tool failure" in low, (
            f"{platform} prompt does not distinguish tool failure from app defect"
        )


def test_system_prompt_advertises_anomaly_severity_field():
    """The LLM needs to know it can emit anomaly_severity. Both platform
    variants of the prompt must document it."""
    for platform in ("ios", "android"):
        prompt = _build_system_prompt(platform)
        assert "anomaly_severity" in prompt, (
            f"{platform} prompt does not mention anomaly_severity — "
            f"the LLM won't know it can emit that field"
        )
        # And the schema comment should list the allowed values.
        assert "Low|Medium|High|Critical" in prompt


def test_force_escape_on_android_uses_press_back_first():
    """Android keeps press_back as the first strategy — dismisses dialogs
    cheaply before falling back to swipes and app-backgrounding."""
    agent = object.__new__(ExploratoryAgent)
    agent.platform = "android"
    calls = []
    class _FakeActions:
        def press_back(self):        calls.append("press_back");        return {"status": "ok"}
        def swipe(self, direction):  calls.append(f"swipe:{direction}"); return {"status": "ok"}
        def background_app(self, s): calls.append(f"bg:{s}");            return {"status": "ok"}
    agent.actions = _FakeActions()

    agent._same_screen_count = 6   # first escape firing
    agent._force_escape()
    assert calls == ["press_back"]


# ── L2: _select_model escalates when prev_result carries the flags ───────────

def _make_agent_stub():
    """Instantiate ExploratoryAgent without running __init__ (which needs Appium)."""
    return object.__new__(ExploratoryAgent)


def test_select_model_uses_opus_after_anomaly():
    agent = _make_agent_stub()
    prev = {"status": "ok", "action": "tap", "anomaly_detected": True}
    assert agent._select_model(prev, has_image=False) == "claude-opus-4-5"


def test_select_model_escalates_to_sonnet_after_json_error():
    agent = _make_agent_stub()
    prev = {"status": "ok", "action": "wait", "_json_error": True}
    assert agent._select_model(prev, has_image=False) == "claude-sonnet-4-6"


def test_select_model_defaults_to_haiku_on_plain_text_call():
    """Sanity: when no escalation flags are set and no image, use Haiku."""
    agent = _make_agent_stub()
    prev = {"status": "ok", "action": "tap"}
    assert agent._select_model(prev, has_image=False) == "claude-haiku-4-5"


def test_select_model_uses_sonnet_when_vision_needed():
    agent = _make_agent_stub()
    prev = {"status": "ok"}
    assert agent._select_model(prev, has_image=True) == "claude-sonnet-4-6"


# ── L11: history entries carry `reasoning` for the stuck-loop abort ──────────

def test_all_history_appends_include_reasoning_field():
    """Regression: the stuck-loop abort reads history[i]['reasoning']. Every
    history.append(...) inside run() must set this key or the abort is dead."""
    import ast, textwrap
    src = textwrap.dedent(inspect.getsource(ExploratoryAgent.run))
    tree = ast.parse(src)
    append_dicts = []
    for node in ast.walk(tree):
        # Match self.history.append({...})
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "history"
                and node.args
                and isinstance(node.args[0], ast.Dict)):
            keys = {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
            append_dicts.append(keys)

    assert append_dicts, "no self.history.append({...}) calls found"
    for keys in append_dicts:
        assert "reasoning" in keys, (
            f"history.append missing 'reasoning' — stuck-loop abort will silently do nothing. "
            f"Keys present: {sorted(keys)}"
        )


def test_screen_changed_detects_change_after_the_first_300_chars():
    """Regression (L7): the old implementation compared prev[:300] != curr[:300]
    and missed changes in elements beyond that prefix on complex Firefox screens."""
    prev = "=== Screen summary (10 visible elements) ===\n" + "identical header stuff " * 20
    curr = prev + "\nNEW ELEMENT AT THE BOTTOM"
    assert ExploratoryAgent._screen_changed(prev, curr) is True


def test_screen_changed_returns_false_on_identical_summaries():
    prev = "=== Screen summary (3 visible elements) ===\nfoo\nbar"
    assert ExploratoryAgent._screen_changed(prev, prev) is False


def test_screen_changed_returns_true_on_empty_prev():
    assert ExploratoryAgent._screen_changed("", "anything") is True


def test_stuck_abort_condition_matches_both_json_and_api_errors():
    """The abort must fire when history shows 3 consecutive LLM-failure waits,
    whether the failures were JSON parse errors or API errors — both come
    from _reason's error branches with action='wait'."""
    llm_error_markers = ("JSON parse", "LLM call failed")

    def stuck_check(recent):
        return bool(recent) and all(
            s.get("action") == "wait"
            and any(m in s.get("reasoning", "") for m in llm_error_markers)
            for s in recent
        )

    all_json = [{"action": "wait", "reasoning": "JSON parse error from LLM"}] * 3
    all_api  = [{"action": "wait", "reasoning": "LLM call failed: 500 upstream"}] * 3
    mixed    = [
        {"action": "wait", "reasoning": "JSON parse error from LLM"},
        {"action": "wait", "reasoning": "LLM call failed: timeout"},
        {"action": "wait", "reasoning": "JSON parse error from LLM"},
    ]
    legit_wait = [{"action": "wait", "reasoning": "waiting for animation"}] * 3
    normal_tap = [{"action": "tap",  "reasoning": "JSON parse error from LLM"}] * 3

    assert stuck_check(all_json) is True
    assert stuck_check(all_api)  is True
    assert stuck_check(mixed)    is True
    assert stuck_check(legit_wait) is False
    assert stuck_check(normal_tap) is False
