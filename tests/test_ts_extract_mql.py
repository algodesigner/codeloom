"""Tests for MQL4/MQL5 extraction.

MQL has no tree-sitter grammar of its own, so it is parsed with the C++
grammar. This mirrors the wider ecosystem: GitHub Linguist maps both
dialects to ``c_cpp``, and ``tree-sitter-mql5`` is itself an extension of
``tree-sitter-cpp``.
"""

from __future__ import annotations

import pytest

from codeloom.core.tags_extract import (
    _LANG_TO_PACKAGE,
    _cache,
    _get_lang_resources,
)
from codeloom.core.ts_extract import extract_file_ts

MQL5_SOURCE = """\
#property copyright "codeloom"
#import "user32.dll"
int MessageBoxW(int h, string text, string caption, int type);
#import

#define MAX_RISK 0.02
input double Lots = 0.1;

class CTradeManager
{
public:
    CTradeManager(double risk) : m_risk(risk) {}
    double CalculateLotSize(double balance);
private:
    double m_risk;
};

struct Signal
{
    int direction;
    double price;
};

double CTradeManager::CalculateLotSize(double balance)
{
    return balance * m_risk;
}

void OnTick()
{
    if (Bid > Ask)
    {
        return;
    }
    for (int i = 0; i < 10; i++)
    {
        Print("tick");
    }
}
"""


@pytest.fixture(autouse=True)
def _clear_tags_cache():
    for lang in ("mql4", "mql5", "cpp"):
        _cache.pop(lang, None)
    yield
    for lang in ("mql4", "mql5", "cpp"):
        _cache.pop(lang, None)


def _require_grammar(language: str) -> None:
    _cache.clear()
    available = _get_lang_resources(language) is not None
    _cache.clear()
    if not available:
        pytest.skip("tree-sitter-cpp not available")


class TestMqlGrammarMapping:
    def test_both_dialects_use_the_cpp_grammar(self):
        assert _LANG_TO_PACKAGE["mql4"] == "cpp"
        assert _LANG_TO_PACKAGE["mql5"] == "cpp"

    @pytest.mark.parametrize("language", ["mql4", "mql5"])
    def test_grammar_resources_load(self, language):
        _require_grammar(language)
        _cache.clear()
        res = _get_lang_resources(language)
        _cache.clear()
        assert res is not None
        assert res["tags_query_str"]


class TestMqlExtraction:
    @pytest.mark.parametrize(
        "language,ext", [("mql4", ".mq4"), ("mql5", ".mq5")]
    )
    def test_extracts_functions_and_classes(self, tmp_path, language, ext):
        _require_grammar(language)
        f = tmp_path / f"sample{ext}"
        f.write_text(MQL5_SOURCE)
        result = extract_file_ts(str(f), language, MQL5_SOURCE)
        names = {n.name for n in result.nodes}
        kinds = {n.kind for n in result.nodes}
        assert "module" in kinds
        assert "class" in kinds
        assert "CTradeManager" in names
        assert "Signal" in names
        assert "OnTick" in names

    def test_extracts_constructor_and_method(self, tmp_path):
        _require_grammar("mql5")
        f = tmp_path / "ea.mq5"
        f.write_text(MQL5_SOURCE)
        result = extract_file_ts(str(f), "mql5", MQL5_SOURCE)
        names = {n.name for n in result.nodes}
        assert any("CalculateLotSize" in n for n in names)

    def test_extracts_event_handlers(self, tmp_path):
        _require_grammar("mql5")
        code = (
            "void OnInit()\n{\n}\n\n"
            "void OnTick()\n{\n}\n\n"
            "void OnDeinit(const int reason)\n{\n}\n"
        )
        f = tmp_path / "events.mq5"
        f.write_text(code)
        result = extract_file_ts(str(f), "mql5", code)
        names = {n.name for n in result.nodes}
        assert {"OnInit", "OnTick", "OnDeinit"} <= names

    def test_extracts_inheritance_edge(self, tmp_path):
        _require_grammar("mql5")
        code = (
            "class Animal\n{\n};\n\n"
            "class Dog : public Animal\n{\n};\n"
        )
        f = tmp_path / "animals.mq5"
        f.write_text(code)
        result = extract_file_ts(str(f), "mql5", code)
        inherits = [e for e in result.edges if e.relation == "inherits"]
        assert any("Animal" in e.target for e in inherits)

    def test_defines_edges_link_module_to_symbols(self, tmp_path):
        _require_grammar("mql5")
        code = "void OnTick()\n{\n}\n"
        f = tmp_path / "tick.mq5"
        f.write_text(code)
        result = extract_file_ts(str(f), "mql5", code)
        defines = [e for e in result.edges if e.relation == "defines"]
        assert defines

    def test_control_flow_is_not_extracted_as_function(self, tmp_path):
        _require_grammar("mql5")
        code = (
            "void OnTick()\n{\n"
            "    if (Bid > Ask)\n    {\n        return;\n    }\n"
            "    for (int i = 0; i < 3; i++)\n    {\n    }\n"
            "}\n"
        )
        f = tmp_path / "flow.mq5"
        f.write_text(code)
        result = extract_file_ts(str(f), "mql5", code)
        names = {n.name for n in result.nodes}
        assert "OnTick" in names
        assert "if" not in names
        assert "for" not in names

    def test_empty_file_does_not_crash(self, tmp_path):
        _require_grammar("mql5")
        f = tmp_path / "empty.mq5"
        f.write_text("")
        result = extract_file_ts(str(f), "mql5", "")
        assert result is not None


def test_pipeline_builds_mql_graph(tmp_path):
    """End-to-end: detect → extract → graph for a .mq5 file."""
    from codeloom.core.pipeline import run_pipeline

    _require_grammar("mql5")
    src = tmp_path / "src"
    src.mkdir()
    (src / "ea.mq5").write_text(MQL5_SOURCE)

    result = run_pipeline(src, output_dir=tmp_path / "out", embed=False)

    labels = {d.get("label") for _, d in result.graph.nodes(data=True)}
    kinds = {d.get("kind") for _, d in result.graph.nodes(data=True)}
    assert "OnTick" in labels
    assert "class" in kinds or "function" in kinds
