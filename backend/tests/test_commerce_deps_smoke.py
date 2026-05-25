"""Smoke tests for commerce-related backend dependencies.

Verifies that ``json-repair`` and ``pyahocorasick`` are importable and that
their core entry points behave as expected. These two libraries underpin
upcoming commerce features:

- ``json_repair``: recovers malformed JSON returned by LLM agents
  (Wave 4 StoryScript drift recovery).
- ``ahocorasick``: powers the multi-pattern compliance rule scanner
  (Wave 3 compliance engine).

Keeping this as an ultra-light smoke test ensures dependency drift or
ABI mismatches surface immediately in CI instead of at runtime.
"""

import json_repair
import ahocorasick


def test_json_repair_recovers_unquoted_keys() -> None:
    """``json_repair`` must recover JSON with unquoted keys into a dict.

    LLM outputs frequently emit JSON-ish payloads with unquoted keys.
    The repair routine should normalise such payloads back into a usable
    Python ``dict`` so downstream parsing does not fail.
    """
    repaired = json_repair.repair_json("{a:1}", return_objects=True)
    assert repaired == {"a": 1}


def test_ahocorasick_basic_match() -> None:
    """``ahocorasick.Automaton`` must match seeded keywords in a haystack.

    This guards the compliance rule engine: we add two keywords, finalise
    the automaton, and confirm both can be located inside a sample text.
    """
    automaton = ahocorasick.Automaton()
    automaton.add_word("foo", ("foo", 1))
    automaton.add_word("bar", ("bar", 2))
    automaton.make_automaton()

    haystack = "the foo and the bar"
    matched = {value for _end, (value, _id) in automaton.iter(haystack)}

    assert matched == {"foo", "bar"}
