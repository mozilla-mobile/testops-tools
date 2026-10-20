"""Tests for android/report.py — payload, rendering, CLI range resolution.

The LLM call is exercised through a stubbed `anthropic` module, so the suite
makes no network requests and costs nothing to run.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from android import budget as bd
from android import change_extractor as ce
from android import gecko_risk as gr
from android import report as rp
from android import scorer as sc
from android import testrail_index as ti


def case(case_id="1", automation="Unsuitable", priority="High", title="t"):
    return ti.TestCase(
        case_id=str(case_id), title=title, section_hierarchy="Homescreen",
        priority=priority, automation=automation, automation_coverage="None",
        case_type="Functional", labels="",
    )


def analysis(**overrides) -> rp.Analysis:
    extraction = overrides.pop("extraction", None) or ce.ExtractionResult(
        base="BASE", head="HEAD",
        files=[ce.ChangedFile("a/X.kt", 5, 1, "code")],
        bugs=[ce.BugChange(bug_id=111111, title="a fix")],
    )
    risk = overrides.pop("risk", None) or gr.GeckoRisk(base="BASE", head="HEAD")
    signal = overrides.pop("signal", None) or bd.BuildSignal(app_product_files=1)
    index = overrides.pop("index", None) or ti.TestRailIndex(
        cases={"1": case("1")}, methods=[], drift=ti.IndexDrift())
    kwargs = dict(
        base="BASE", head="HEAD", extraction=extraction, risk=risk,
        budget=bd.compute_budget(signal), signal=signal, index=index,
        priorities={"P0": [], "P1": [], "P2": []},
    )
    kwargs.update(overrides)
    return rp.Analysis(**kwargs)


# =============================================================================
# Payload
# =============================================================================


class TestBuildPayload(unittest.TestCase):
    def test_includes_the_decided_test_list(self):
        a = analysis(
            index=ti.TestRailIndex(cases={"1": case("1", title="Check X")},
                                   methods=[], drift=ti.IndexDrift()),
            priorities={"P0": [sc.ScoredCase("1", "Homescreen", 40, ["why"])],
                        "P1": [], "P2": []},
        )
        payload = rp.build_payload(a)
        self.assertEqual(payload["suggested_tests"]["P0"][0]["case_id"], "C1")
        self.assertEqual(payload["suggested_tests"]["P0"][0]["title"], "Check X")
        self.assertEqual(payload["suggested_tests"]["P0"][0]["why"], ["why"])

    def test_carries_the_veto_so_the_model_cannot_miss_it(self):
        risk = gr.GeckoRisk(
            base="B", head="H",
            areas=[gr.GeckoArea("dom", [gr.ChangedFile("dom/X.cpp", 900, 0, "code")])])
        a = analysis(risk=risk, signal=bd.BuildSignal(
            app_product_files=0, engine_is_material=True))
        self.assertTrue(rp.build_payload(a)["engine"]["vetoes_no_regression_claim"])

    def test_budget_rationale_is_included_for_audit(self):
        payload = rp.build_payload(analysis())
        self.assertIn("Test budget:", payload["budget"]["rationale"])

    def test_skips_cases_missing_from_the_index(self):
        a = analysis(priorities={"P0": [sc.ScoredCase("999", "S", 10, [])],
                                 "P1": [], "P2": []})
        self.assertEqual(rp.build_payload(a)["suggested_tests"]["P0"], [])

    def test_serialises_to_json(self):
        import json
        json.dumps(rp.build_payload(analysis()), default=str)


# =============================================================================
# Deterministic render
# =============================================================================


class TestRenderDeterministic(unittest.TestCase):
    def test_has_the_expected_sections(self):
        text = rp.render_deterministic(analysis())
        for heading in ("# Firefox Android", "## What changed",
                        "## Suggested manual tests", "### P0"):
            self.assertIn(heading, text)

    def test_states_the_veto_prominently(self):
        risk = gr.GeckoRisk(
            base="B", head="H",
            areas=[gr.GeckoArea("dom", [gr.ChangedFile("dom/X.cpp", 900, 0, "code")])])
        text = rp.render_deterministic(analysis(
            risk=risk,
            signal=bd.BuildSignal(app_product_files=0, engine_is_material=True)))
        self.assertIn("app diff is quiet but the engine moved", text)

    def test_empty_tranche_says_so_rather_than_rendering_an_empty_table(self):
        self.assertIn("_No P0 cases._", rp.render_deterministic(analysis()))

    def test_pipes_in_titles_are_escaped(self):
        a = analysis(
            index=ti.TestRailIndex(cases={"1": case("1", title="a | b")},
                                   methods=[], drift=ti.IndexDrift()),
            priorities={"P0": [sc.ScoredCase("1", "S", 40, [])], "P1": [], "P2": []},
        )
        self.assertIn(r"a \| b", rp.render_deterministic(a))

    def test_nimbus_section_warns_about_new_user_targeting(self):
        a = analysis(nimbus_features=["homescreen"], nimbus_slugs=["exp-1"])
        self.assertIn("will not reproduce on an upgraded profile",
                      rp.render_deterministic(a))


# =============================================================================
# Synthesis fallbacks
# =============================================================================


class TestSynthesizeFallbacks(unittest.TestCase):
    """Every failure path must still produce a report."""

    def test_missing_sdk_falls_back(self):
        with mock.patch.object(rp, "anthropic", None):
            text = rp.synthesize(analysis())
        self.assertIn("deterministic mode", text)

    def test_api_error_falls_back(self):
        fake = mock.MagicMock()
        fake.Anthropic.return_value.messages.stream.side_effect = RuntimeError("boom")
        with mock.patch.object(rp, "anthropic", fake):
            text = rp.synthesize(analysis())
        self.assertIn("deterministic mode", text)

    def test_refusal_falls_back(self):
        message = mock.MagicMock(stop_reason="refusal")
        fake = mock.MagicMock()
        stream = fake.Anthropic.return_value.messages.stream.return_value
        stream.__enter__.return_value.get_final_message.return_value = message
        with mock.patch.object(rp, "anthropic", fake):
            text = rp.synthesize(analysis())
        self.assertIn("deterministic mode", text)

    def test_empty_response_falls_back(self):
        message = mock.MagicMock(stop_reason="end_turn", content=[])
        fake = mock.MagicMock()
        stream = fake.Anthropic.return_value.messages.stream.return_value
        stream.__enter__.return_value.get_final_message.return_value = message
        with mock.patch.object(rp, "anthropic", fake):
            text = rp.synthesize(analysis())
        self.assertIn("deterministic mode", text)

    def test_success_appends_a_provenance_footer(self):
        block = mock.MagicMock(type="text", text="## Executive summary\n\nFine.")
        message = mock.MagicMock(stop_reason="end_turn", content=[block])
        message.usage.input_tokens = 10
        message.usage.output_tokens = 20
        fake = mock.MagicMock()
        stream = fake.Anthropic.return_value.messages.stream.return_value
        stream.__enter__.return_value.get_final_message.return_value = message
        with mock.patch.object(rp, "anthropic", fake):
            text = rp.synthesize(analysis(), model="claude-opus-5")
        self.assertIn("Fine.", text)
        self.assertIn("Test selection is deterministic", text)
        self.assertIn("claude-opus-5", text)

    def test_uses_adaptive_thinking_and_caches_the_system_prompt(self):
        block = mock.MagicMock(type="text", text="x")
        message = mock.MagicMock(stop_reason="end_turn", content=[block])
        message.usage.input_tokens = 1
        message.usage.output_tokens = 1
        fake = mock.MagicMock()
        stream_fn = fake.Anthropic.return_value.messages.stream
        stream_fn.return_value.__enter__.return_value.get_final_message.return_value = message
        with mock.patch.object(rp, "anthropic", fake):
            rp.synthesize(analysis())
        kwargs = stream_fn.call_args.kwargs
        self.assertEqual(kwargs["thinking"], {"type": "adaptive"})
        self.assertEqual(kwargs["system"][0]["cache_control"], {"type": "ephemeral"})


# =============================================================================
# CLI
# =============================================================================


class _Args:
    def __init__(self, **kw):
        self.from_tag = kw.get("from_tag")
        self.to_tag = kw.get("to_tag")
        self.cycle = kw.get("cycle")
        self.beta = kw.get("beta")
        self.rc = kw.get("rc", False)


class TestResolveRange(unittest.TestCase):
    TAGS = "\n".join([
        "FIREFOX-ANDROID_159_0b1_RELEASE",
        "FIREFOX-ANDROID_159_0b2_RELEASE",
        "FIREFOX-ANDROID_159_0b3_RELEASE",
        "FIREFOX-ANDROID_159_0_BUILD1",
        "FIREFOX-ANDROID_160_0b1_RELEASE",
    ])

    def setUp(self):
        self._real_git = ce._git
        ce._git = lambda repo, args: self.TAGS

    def tearDown(self):
        ce._git = self._real_git

    def test_explicit_tags_pass_through(self):
        self.assertEqual(
            rp.resolve_range("r", _Args(from_tag="A", to_tag="B")), ("A", "B"))

    def test_cycle_defaults_to_the_most_recent_pair(self):
        base, head = rp.resolve_range("r", _Args(cycle=159))
        self.assertTrue(base.endswith("0b2_RELEASE"))
        self.assertTrue(head.endswith("0b3_RELEASE"))

    def test_specific_beta(self):
        base, _ = rp.resolve_range("r", _Args(cycle=159, beta=1))
        self.assertTrue(base.endswith("0b1_RELEASE"))

    def test_rc_compares_final_beta_to_rc(self):
        base, head = rp.resolve_range("r", _Args(cycle=159, rc=True))
        self.assertTrue(base.endswith("0b3_RELEASE"))
        self.assertTrue(head.endswith("0_BUILD1"))

    def test_single_beta_cycle_explains_itself(self):
        """160 has one beta, so there is no beta-to-beta range yet."""
        with self.assertRaises(SystemExit) as ctx:
            rp.resolve_range("r", _Args(cycle=160))
        self.assertIn("fewer than two betas", str(ctx.exception))

    def test_unknown_beta_lists_what_is_available(self):
        with self.assertRaises(SystemExit) as ctx:
            rp.resolve_range("r", _Args(cycle=159, beta=9))
        self.assertIn("Available:", str(ctx.exception))

    def test_no_arguments_is_an_error(self):
        with self.assertRaises(SystemExit):
            rp.resolve_range("r", _Args())


class TestDefaultOutputName(unittest.TestCase):
    def test_matches_the_gitignored_report_pattern(self):
        name = rp.default_output_name("FIREFOX-ANDROID_159_0b1_BUILD1",
                                      "FIREFOX-ANDROID_159_0b1_BUILD2")
        self.assertTrue(name.startswith("release_report_"))
        self.assertTrue(name.endswith(".md"))
        self.assertIn("159.0b1-build1", name)
        self.assertIn("159.0b1-build2", name)

    def test_unparseable_tag_is_used_verbatim(self):
        self.assertIn("whatever", rp.default_output_name("whatever", "else"))


if __name__ == "__main__":
    unittest.main()
