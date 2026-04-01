from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from query_opm_nl import build_component_url_from_binding, select_component_binding  # noqa: E402


class ComponentUrlRegistryTests(unittest.TestCase):
    def test_select_component_binding_for_margin_query(self) -> None:
        binding = select_component_binding(
            report_name="航空集团经营提升分析",
            metric_hint="单机边际贡献",
            intent_metric="单机边际贡献",
            raw_query="各航司3月单机边际贡献，同比起来谁最好",
        )
        self.assertIsNotNone(binding)
        self.assertEqual(binding["report_match"], "航空集团经营提升分析")
        self.assertIn("单机边际贡献", binding["metric_keywords"])

    def test_build_component_url_renders_parameters(self) -> None:
        binding = {
            "viewlet": "/doc/Fdjt/marketOperSup/航空集团经营提升分析/2单机边际贡献-宽体机.cpt",
            "op": "form_adaptive",
            "parameter_map": {
                "date_s": "{date_start}",
                "date_e": "{date_end}",
                "date_s_tq": "{date_start_prev_year}",
                "date_e_tq": "{date_end_prev_year}",
                "comp_name": "{company|}",
            },
        }
        url = build_component_url_from_binding(
            binding,
            filters={
                "date_start": "2026-03-01",
                "date_end": "2026-03-31",
                "company": "航空股份",
            },
        )
        self.assertIsNotNone(url)
        parsed = urlparse(url or "")
        qs = parse_qs(parsed.query)
        self.assertEqual(unquote(qs["viewlet"][0]), binding["viewlet"])
        self.assertEqual(unquote(qs["op"][0]), "form_adaptive")
        params = json.loads(unquote(qs["__parameters__"][0]))
        self.assertEqual(
            params,
            {
                "date_s": "2026-03-01",
                "date_e": "2026-03-31",
                "date_s_tq": "2025-03-01",
                "date_e_tq": "2025-03-31",
                "comp_name": "航空股份",
            },
        )

    def test_build_component_url_uses_default_value_when_filter_missing(self) -> None:
        binding = {
            "viewlet": "/doc/Fdjt/marketOperSup/航空集团经营提升分析/2单机边际贡献-宽体机.cpt",
            "parameter_map": {
                "comp_name": "{company|}",
            },
        }
        url = build_component_url_from_binding(binding, filters={})
        parsed = urlparse(url or "")
        qs = parse_qs(parsed.query)
        params = json.loads(unquote(qs["__parameters__"][0]))
        self.assertEqual(params["comp_name"], "")


if __name__ == "__main__":
    unittest.main()
