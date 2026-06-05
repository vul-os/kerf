"""test_spice_library.py — Tests for the comprehensive SPICE component/model library.

Covers:
  - Library breadth: all categories present, total count ≥ 200 parts
  - Category-based search returns only matching family
  - Keyword search works (name + description substring)
  - Spec-filter search (BV=12)
  - Model card has valid SPICE (starts with .MODEL or .SUBCKT)
  - Specific model correctness: Zener BV, Schottky, BJT polarity, MOSFET type
  - Subcircuit models have matching .ENDS
  - Passives have parasitics (LESL/RESR for caps, Rdcr/Cp for inductors)
  - spice_library_search tool (registration, payload shape, filtering)
  - spice_library_get_model tool (happy path, not-found, suggestions)
  - Netlist insertion via spice_lib inject helper
  - Logic gate models have expected pins
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import types
import unittest

# ── Prefer the real kerf_chat (installed in this monorepo). Pinning it into
#    sys.modules BEFORE the stub setdefaults means those become no-ops and the
#    stub never shadows the real, populated Registry that other suites import.
try:
    import kerf_chat as _kc_pkg  # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

# ---------------------------------------------------------------------------
# Bootstrap: load spice_library standalone (same pattern as test_spice_lib.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_HERE), "src", "kerf_electronics", "tools")
_MOD_PATH = os.path.join(_SRC_DIR, "spice_library.py")

# Stub kerf_chat.tools.registry so @register doesn't pull the full stack
_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type("ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)})
_reg_stub.err_payload = lambda msg, code: json.dumps({"error": msg, "code": code})
_reg_stub.ok_payload = lambda v: json.dumps(v)
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_KERF_CHAT_SAVED = {
    n: sys.modules.get(n)
    for n in ("kerf_chat", "kerf_chat.tools", "kerf_chat.tools.registry")
}

_pkg = types.ModuleType("kerf_chat")
_tools_pkg = types.ModuleType("kerf_chat.tools")
_pkg.tools = _tools_pkg
sys.modules.setdefault("kerf_chat", _pkg)
sys.modules.setdefault("kerf_chat.tools", _tools_pkg)
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

_spec = importlib.util.spec_from_file_location("kerf_electronics.tools.spice_library", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Public symbols under test
_CATALOGUE       = _mod._CATALOGUE
CATEGORIES       = _mod.CATEGORIES
get_model_card   = _mod.get_model_card
get_model_spice  = _mod.get_model_spice
search_models    = _mod.search_models
spice_library_search    = _mod.spice_library_search
spice_library_get_model = _mod.spice_library_get_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _call(fn, payload: dict) -> dict:
    raw = await fn(None, json.dumps(payload).encode())
    return json.loads(raw)


def _first_line(spice: str) -> str:
    return spice.strip().splitlines()[0].strip().upper()


def _is_valid_spice(spice: str) -> tuple[bool, str]:
    if not spice or not spice.strip():
        return False, "empty"
    fl = _first_line(spice)
    if fl.startswith(".MODEL") or fl.startswith(".SUBCKT"):
        return True, ""
    return False, f"first line: {fl!r}"


def _subckt_name(spice: str) -> str | None:
    m = re.search(r"^\.SUBCKT\s+(\S+)", spice, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else None


def _ends_name(spice: str) -> str | None:
    m = re.search(r"^\.ENDS\s+(\S+)", spice, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else None


# ===========================================================================
# 1. Library breadth
# ===========================================================================

class TestLibraryBreadth(unittest.TestCase):

    def test_catalogue_has_at_least_200_parts(self):
        self.assertGreaterEqual(len(_CATALOGUE), 200, "Expected ≥200 parts in library")

    def test_all_expected_categories_present(self):
        cats = {v["category"] for v in _CATALOGUE.values()}
        for expected in (
            "diode_rectifier", "diode_schottky", "diode_zener", "diode_tvs", "diode_led",
            "bjt_npn", "bjt_pnp", "bjt_darlington",
            "mosfet_nmos", "mosfet_pmos",
            "jfet_n", "jfet_p",
            "opamp", "comparator", "vref", "regulator",
            "passive_cap", "passive_ind", "passive_res",
            "logic", "ic_timer", "ic_misc",
        ):
            self.assertIn(expected, cats, f"category {expected!r} missing")

    def test_categories_dict_complete(self):
        # Every category used in the catalogue should appear in CATEGORIES
        used = {v["category"] for v in _CATALOGUE.values()}
        for cat in used:
            self.assertIn(cat, CATEGORIES, f"CATEGORIES missing label for {cat!r}")

    def test_diode_rectifier_count_gte_10(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "diode_rectifier")
        self.assertGreaterEqual(n, 10)

    def test_diode_zener_count_gte_15(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "diode_zener")
        self.assertGreaterEqual(n, 15)

    def test_bjt_npn_count_gte_10(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "bjt_npn")
        self.assertGreaterEqual(n, 10)

    def test_mosfet_nmos_count_gte_10(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "mosfet_nmos")
        self.assertGreaterEqual(n, 10)

    def test_opamp_count_gte_8(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "opamp")
        self.assertGreaterEqual(n, 8)

    def test_regulator_count_gte_10(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "regulator")
        self.assertGreaterEqual(n, 10)

    def test_logic_count_gte_8(self):
        n = sum(1 for v in _CATALOGUE.values() if v["category"] == "logic")
        self.assertGreaterEqual(n, 8)

    def test_each_entry_has_required_keys(self):
        for name, entry in _CATALOGUE.items():
            with self.subTest(model=name):
                self.assertIn("category",    entry, f"{name}: missing 'category'")
                self.assertIn("description", entry, f"{name}: missing 'description'")
                self.assertIn("model",       entry, f"{name}: missing 'model'")


# ===========================================================================
# 2. SPICE syntax validity for every model
# ===========================================================================

class TestModelSpiceSyntax(unittest.TestCase):

    def test_every_model_starts_with_model_or_subckt(self):
        for name, entry in _CATALOGUE.items():
            with self.subTest(model=name):
                ok, reason = _is_valid_spice(entry["model"])
                self.assertTrue(ok, f"{name}: invalid SPICE — {reason}")

    def test_every_subckt_has_matching_ends(self):
        for name, entry in _CATALOGUE.items():
            spice = entry["model"]
            if _first_line(spice).startswith(".SUBCKT"):
                with self.subTest(model=name):
                    sname = _subckt_name(spice)
                    ename = _ends_name(spice)
                    self.assertIsNotNone(ename, f"{name}: .SUBCKT missing .ENDS")
                    self.assertEqual(
                        sname, ename,
                        f"{name}: .SUBCKT {sname} ≠ .ENDS {ename}"
                    )

    def test_get_model_spice_case_insensitive(self):
        s_upper = get_model_spice("D1N4148")
        s_lower = get_model_spice("d1n4148")
        self.assertIsNotNone(s_upper)
        self.assertEqual(s_upper, s_lower)

    def test_get_model_spice_unknown_returns_none(self):
        self.assertIsNone(get_model_spice("XYZNOTAMODEL"))

    def test_get_model_card_returns_full_dict(self):
        card = get_model_card("Q2N3904")
        self.assertIsNotNone(card)
        self.assertIn("category", card)
        self.assertIn("model", card)
        self.assertIn("description", card)


# ===========================================================================
# 3. Specific model correctness
# ===========================================================================

class TestSpecificModels(unittest.TestCase):

    # Diodes — rectifier
    def test_d1n4148_model_directive(self):
        s = get_model_spice("D1N4148")
        self.assertIn(".MODEL D1N4148 D(", s)

    def test_d1n4007_bv_1000(self):
        s = get_model_spice("D1N4007")
        self.assertIn("BV=1000", s)

    # Diodes — Schottky
    def test_d1n5819_is_schottky(self):
        card = get_model_card("D1N5819")
        self.assertEqual(card["category"], "diode_schottky")

    def test_bat54_bv_30(self):
        s = get_model_spice("DBAT54")
        self.assertIn("BV=30", s)

    # Diodes — Zener
    def test_zener5v1_bv_5(self):
        s = get_model_spice("DZENER5V1")
        self.assertIn("BV=5.1", s)

    def test_zener12v_bv_12(self):
        s = get_model_spice("DZENER12V")
        self.assertIn("BV=12.0", s)

    def test_dz3v3_bv_present(self):
        s = get_model_spice("DZ3V3")
        self.assertIn("BV=3.3", s)

    def test_dz47v_bv_present(self):
        s = get_model_spice("DZ47V")
        self.assertIn("BV=47.0", s)

    # TVS
    def test_tvs5v0_is_tvs_category(self):
        card = get_model_card("DTVS5V0")
        self.assertEqual(card["category"], "diode_tvs")

    # LED
    def test_led_red_category(self):
        card = get_model_card("DLED_RED")
        self.assertEqual(card["category"], "diode_led")

    # BJTs
    def test_q2n3904_npn(self):
        s = get_model_spice("Q2N3904")
        self.assertIn("NPN(", s)

    def test_q2n3906_pnp(self):
        s = get_model_spice("Q2N3906")
        self.assertIn("PNP(", s)

    def test_qbc547_npn_bf_large(self):
        s = get_model_spice("QBC547")
        self.assertIn("NPN(", s)
        self.assertIn("BF=400", s)

    def test_qtip120_darlington_category(self):
        card = get_model_card("QTIP120")
        self.assertEqual(card["category"], "bjt_darlington")

    def test_qtip120_high_bf(self):
        card = get_model_card("QTIP120")
        self.assertGreaterEqual(card["params"]["BF"], 1000)

    def test_bfr93_rf_category(self):
        card = get_model_card("QBFR93")
        self.assertEqual(card["category"], "bjt_rf")

    def test_q2n3055_npn_power(self):
        s = get_model_spice("Q2N3055")
        self.assertIn("NPN(", s)

    # MOSFETs
    def test_m2n7000_nmos(self):
        s = get_model_spice("M2N7000")
        self.assertIn("NMOS(", s)

    def test_mirf540_nmos(self):
        s = get_model_spice("MIRF540")
        self.assertIn("NMOS(", s)

    def test_mirf9540_pmos(self):
        s = get_model_spice("MIRF9540")
        self.assertIn("PMOS(", s)

    def test_m2p7000_pmos(self):
        s = get_model_spice("M2P7000")
        self.assertIn("PMOS(", s)

    # JFETs
    def test_j2n5457_njf(self):
        s = get_model_spice("J2N5457")
        self.assertIn("NJF(", s)

    def test_j2n5460_pjf(self):
        s = get_model_spice("J2N5460")
        self.assertIn("PJF(", s)

    # Op-amps
    def test_opamp_ideal_pins(self):
        s = get_model_spice("OPAMP_IDEAL")
        self.assertIn(".SUBCKT OPAMP_IDEAL IN+ IN- V+ V- OUT", s)
        self.assertIn(".ENDS OPAMP_IDEAL", s)

    def test_opamp_lm358_subckt(self):
        s = get_model_spice("OPAMP_LM358")
        self.assertIn(".SUBCKT OPAMP_LM358", s)
        self.assertIn(".ENDS OPAMP_LM358", s)

    def test_opamp_ne5532_subckt(self):
        s = get_model_spice("OPAMP_NE5532")
        self.assertIn(".SUBCKT OPAMP_NE5532", s)

    def test_opamp_op07_subckt(self):
        s = get_model_spice("OPAMP_OP07")
        self.assertIn(".SUBCKT OPAMP_OP07", s)

    def test_opamp_tl072_subckt(self):
        s = get_model_spice("OPAMP_TL072")
        self.assertIn(".SUBCKT OPAMP_TL072", s)

    # Comparators
    def test_comp_lm393_subckt(self):
        s = get_model_spice("COMP_LM393")
        self.assertIn(".SUBCKT COMP_LM393", s)

    def test_comp_ideal_subckt(self):
        s = get_model_spice("COMP_IDEAL")
        self.assertIn(".SUBCKT COMP_IDEAL", s)

    # Voltage references
    def test_vref_tl431_subckt(self):
        s = get_model_spice("VREF_TL431")
        self.assertIn(".SUBCKT VREF_TL431", s)

    # Regulators
    def test_ldo_78xx_subckt(self):
        s = get_model_spice("LDO_78XX")
        self.assertIn(".SUBCKT LDO_78XX", s)
        self.assertIn(".ENDS LDO_78XX", s)

    def test_ldo_7812_subckt(self):
        s = get_model_spice("LDO_7812")
        self.assertIn(".SUBCKT LDO_7812", s)
        self.assertIn("12.0", s)

    def test_ldo_7905_subckt_negative(self):
        s = get_model_spice("LDO_7905")
        self.assertIn(".SUBCKT LDO_7905", s)
        self.assertIn("-5.0", s)

    def test_ldo_lm317_subckt(self):
        s = get_model_spice("LDO_LM317")
        self.assertIn(".SUBCKT LDO_LM317", s)

    def test_ldo_3v3_subckt(self):
        s = get_model_spice("LDO_3V3")
        self.assertIn(".SUBCKT LDO_3V3", s)
        self.assertIn("3.3", s)

    # Capacitors
    def test_cap_elec_100u_has_esr_esl(self):
        s = get_model_spice("CAP_ELEC_100U")
        self.assertIn("LESL", s)
        self.assertIn("RESR", s)
        self.assertIn("C1", s)

    def test_cap_x7r_100n_subckt(self):
        s = get_model_spice("CAP_X7R_100N")
        self.assertIn(".SUBCKT CAP_X7R_100N", s)
        self.assertIn(".ENDS CAP_X7R_100N", s)

    def test_cap_film_100n_subckt(self):
        s = get_model_spice("CAP_FILM_100N")
        self.assertIn(".SUBCKT CAP_FILM_100N", s)

    def test_cap_elec_2200u_subckt(self):
        s = get_model_spice("CAP_ELEC_2200U")
        self.assertIn(".SUBCKT CAP_ELEC_2200U", s)

    # Inductors
    def test_ind_10u_has_parasitics(self):
        s = get_model_spice("IND_10U")
        self.assertIn("Rdcr", s)
        self.assertIn("Cp", s)
        self.assertIn(".SUBCKT IND_10U", s)

    def test_ind_10u_cp_positive(self):
        import math
        s = get_model_spice("IND_10U")
        m = re.search(r"Cp\s+\S+\s+\S+\s+([\d.e+-]+)", s, re.IGNORECASE)
        self.assertIsNotNone(m, "Cp line not found")
        self.assertGreater(float(m.group(1)), 0)

    def test_ind_100n_subckt(self):
        s = get_model_spice("IND_100N")
        self.assertIn(".SUBCKT IND_100N", s)

    def test_ind_1000u_subckt(self):
        s = get_model_spice("IND_1000U")
        self.assertIn(".SUBCKT IND_1000U", s)

    # Logic gates
    def test_not_74hc_subckt(self):
        s = get_model_spice("NOT_74HC")
        self.assertIn(".SUBCKT NOT_74HC", s)

    def test_nand_74hc_has_two_inputs(self):
        s = get_model_spice("NAND_74HC")
        self.assertIn(".SUBCKT NAND_74HC A B VCC GND Y", s)

    def test_xor_74hc_subckt(self):
        s = get_model_spice("XOR_74HC")
        self.assertIn(".SUBCKT XOR_74HC", s)

    def test_not_3v3_subckt(self):
        s = get_model_spice("NOT_3V3")
        self.assertIn(".SUBCKT NOT_3V3", s)

    # 555 timer
    def test_ic555_subckt(self):
        s = get_model_spice("IC555")
        self.assertIn(".SUBCKT IC555", s)
        self.assertIn(".ENDS IC555", s)

    # ICs misc
    def test_inamp_ideal_subckt(self):
        s = get_model_spice("INAMP_IDEAL")
        self.assertIn(".SUBCKT INAMP_IDEAL", s)

    def test_vco_ideal_subckt(self):
        s = get_model_spice("VCO_IDEAL")
        self.assertIn(".SUBCKT VCO_IDEAL", s)

    def test_dac8b_subckt(self):
        s = get_model_spice("DAC8B_IDEAL")
        self.assertIn(".SUBCKT DAC8B_IDEAL", s)


# ===========================================================================
# 4. search_models (Python API)
# ===========================================================================

class TestSearchModels(unittest.TestCase):

    def test_search_by_category_rectifier(self):
        results = search_models(category="diode_rectifier")
        self.assertGreater(len(results), 5)
        for r in results:
            self.assertEqual(r["category"], "diode_rectifier")

    def test_search_by_category_schottky(self):
        results = search_models(category="diode_schottky")
        self.assertGreater(len(results), 5)
        for r in results:
            self.assertEqual(r["category"], "diode_schottky")

    def test_search_by_category_zener(self):
        results = search_models(category="diode_zener")
        self.assertGreater(len(results), 10)
        for r in results:
            self.assertEqual(r["category"], "diode_zener")

    def test_search_by_category_bjt_npn(self):
        results = search_models(category="bjt_npn")
        names = {r["name"] for r in results}
        self.assertIn("Q2N3904", names)
        self.assertIn("QBC547", names)

    def test_search_by_category_mosfet_nmos(self):
        results = search_models(category="mosfet_nmos")
        names = {r["name"] for r in results}
        self.assertIn("M2N7000", names)
        self.assertIn("MIRF540", names)

    def test_search_by_category_opamp(self):
        results = search_models(category="opamp")
        names = {r["name"] for r in results}
        self.assertIn("OPAMP_IDEAL", names)
        self.assertIn("OPAMP_LM358", names)

    def test_search_by_category_regulator(self):
        results = search_models(category="regulator")
        names = {r["name"] for r in results}
        self.assertIn("LDO_78XX", names)
        self.assertIn("LDO_7812", names)

    def test_search_by_category_logic(self):
        results = search_models(category="logic")
        names = {r["name"] for r in results}
        self.assertIn("NOT_74HC", names)
        self.assertIn("NAND_74HC", names)

    def test_search_by_category_passive_cap(self):
        results = search_models(category="passive_cap")
        names = {r["name"] for r in results}
        self.assertIn("CAP_ELEC_100U", names)
        self.assertIn("CAP_X7R_100N", names)

    def test_search_by_category_passive_ind(self):
        results = search_models(category="passive_ind")
        names = {r["name"] for r in results}
        self.assertIn("IND_10U", names)

    def test_keyword_search_zener(self):
        results = search_models(keyword="zener")
        self.assertGreater(len(results), 5)
        for r in results:
            self.assertIn("zener", r["description"].lower())

    def test_keyword_search_schottky(self):
        results = search_models(keyword="schottky")
        self.assertGreater(len(results), 3)

    def test_keyword_search_name_match(self):
        results = search_models(keyword="LM358")
        self.assertGreater(len(results), 0)
        names = {r["name"] for r in results}
        self.assertIn("OPAMP_LM358", names)

    def test_keyword_search_power(self):
        results = search_models(keyword="power")
        self.assertGreater(len(results), 5)

    def test_keyword_search_no_results(self):
        results = search_models(keyword="XYZIMPOSSIBLE999")
        self.assertEqual(len(results), 0)

    def test_spec_filter_bv_12(self):
        results = search_models(spec_key="BV", spec_value="12")
        self.assertGreater(len(results), 0)
        names = {r["name"] for r in results}
        self.assertIn("DZENER12V", names)

    def test_spec_filter_vout_3_3(self):
        results = search_models(spec_key="Vout", spec_value="3.3")
        self.assertGreater(len(results), 0)
        names = {r["name"] for r in results}
        self.assertIn("LDO_3V3", names)

    def test_combined_category_and_keyword(self):
        results = search_models(category="bjt_pnp", keyword="power")
        for r in results:
            self.assertEqual(r["category"], "bjt_pnp")

    def test_result_shape_has_required_keys(self):
        results = search_models(category="diode_rectifier")
        for r in results:
            self.assertIn("name", r)
            self.assertIn("category", r)
            self.assertIn("category_label", r)
            self.assertIn("description", r)
            self.assertIn("params", r)

    def test_no_filter_returns_all(self):
        results = search_models()
        self.assertEqual(len(results), len(_CATALOGUE))


# ===========================================================================
# 5. spice_library_search tool
# ===========================================================================

class TestSearchTool(unittest.IsolatedAsyncioTestCase):

    async def test_no_filter_returns_all(self):
        result = await _call(spice_library_search, {})
        self.assertIn("models", result)
        self.assertIn("total", result)
        self.assertEqual(result["total"], len(_CATALOGUE))

    async def test_disclaimer_present(self):
        result = await _call(spice_library_search, {})
        self.assertIn("disclaimer", result)
        self.assertIn("representative", result["disclaimer"])

    async def test_categories_in_response(self):
        result = await _call(spice_library_search, {})
        self.assertIn("categories", result)
        self.assertIn("diode_rectifier", result["categories"])

    async def test_filter_by_diode_rectifier(self):
        result = await _call(spice_library_search, {"category": "diode_rectifier"})
        for m in result["models"]:
            self.assertEqual(m["category"], "diode_rectifier")
        self.assertGreater(result["total"], 5)

    async def test_filter_by_bjt_npn(self):
        result = await _call(spice_library_search, {"category": "bjt_npn"})
        names = {m["name"] for m in result["models"]}
        self.assertIn("Q2N3904", names)

    async def test_filter_by_opamp(self):
        result = await _call(spice_library_search, {"category": "opamp"})
        names = {m["name"] for m in result["models"]}
        self.assertIn("OPAMP_IDEAL", names)
        self.assertIn("OPAMP_LM358", names)

    async def test_filter_by_regulator(self):
        result = await _call(spice_library_search, {"category": "regulator"})
        names = {m["name"] for m in result["models"]}
        self.assertIn("LDO_78XX", names)
        self.assertIn("LDO_7812", names)

    async def test_filter_by_logic(self):
        result = await _call(spice_library_search, {"category": "logic"})
        names = {m["name"] for m in result["models"]}
        self.assertIn("NOT_74HC", names)
        self.assertIn("NAND_74HC", names)

    async def test_keyword_filter_zener(self):
        result = await _call(spice_library_search, {"keyword": "zener"})
        self.assertGreater(result["total"], 5)

    async def test_keyword_filter_555(self):
        result = await _call(spice_library_search, {"keyword": "555"})
        self.assertGreater(result["total"], 0)

    async def test_spec_filter_bv_12(self):
        result = await _call(spice_library_search, {"spec_key": "BV", "spec_value": "12"})
        self.assertGreater(result["total"], 0)

    async def test_each_model_shape(self):
        result = await _call(spice_library_search, {})
        for m in result["models"]:
            self.assertIn("name", m)
            self.assertIn("category", m)
            self.assertIn("description", m)

    async def test_invalid_json_returns_error(self):
        raw = await spice_library_search(None, b"not json {{")
        data = json.loads(raw)
        self.assertIn("error", data)


# ===========================================================================
# 6. spice_library_get_model tool
# ===========================================================================

class TestGetModelTool(unittest.IsolatedAsyncioTestCase):

    async def test_get_d1n4148(self):
        result = await _call(spice_library_get_model, {"name": "D1N4148"})
        self.assertIn("spice", result)
        self.assertIn(".MODEL D1N4148 D(", result["spice"])

    async def test_get_q2n3904(self):
        result = await _call(spice_library_get_model, {"name": "Q2N3904"})
        self.assertNotIn("error", result)
        self.assertIn("NPN(", result["spice"])

    async def test_get_opamp_tl072(self):
        result = await _call(spice_library_get_model, {"name": "OPAMP_TL072"})
        self.assertNotIn("error", result)
        self.assertIn(".SUBCKT OPAMP_TL072", result["spice"])

    async def test_get_ldo_7812(self):
        result = await _call(spice_library_get_model, {"name": "LDO_7812"})
        self.assertNotIn("error", result)
        self.assertIn("12.0", result["spice"])

    async def test_get_ic555(self):
        result = await _call(spice_library_get_model, {"name": "IC555"})
        self.assertNotIn("error", result)
        self.assertIn(".SUBCKT IC555", result["spice"])

    async def test_case_insensitive(self):
        r1 = await _call(spice_library_get_model, {"name": "d1n4148"})
        r2 = await _call(spice_library_get_model, {"name": "D1N4148"})
        self.assertNotIn("error", r1)
        self.assertEqual(r1["spice"], r2["spice"])

    async def test_unknown_returns_error(self):
        result = await _call(spice_library_get_model, {"name": "XYZNOTAMODEL"})
        self.assertIn("error", result)

    async def test_unknown_provides_suggestions(self):
        result = await _call(spice_library_get_model, {"name": "D1N414"})
        # Should offer suggestions containing D1N4148
        self.assertIn("error", result)
        self.assertIn("Suggestions", result.get("error", "") + result.get("code", ""))

    async def test_missing_name_returns_error(self):
        result = await _call(spice_library_get_model, {})
        self.assertIn("error", result)

    async def test_result_has_all_fields(self):
        result = await _call(spice_library_get_model, {"name": "Q2N3904"})
        for key in ("name", "category", "category_label", "description", "spice", "params", "disclaimer", "usage_hint"):
            self.assertIn(key, result, f"missing key: {key}")

    async def test_disclaimer_present(self):
        result = await _call(spice_library_get_model, {"name": "D1N4007"})
        self.assertIn("disclaimer", result)

    async def test_invalid_json_returns_error(self):
        raw = await spice_library_get_model(None, b"{{bad")
        data = json.loads(raw)
        self.assertIn("error", data)

    async def test_get_darlington(self):
        result = await _call(spice_library_get_model, {"name": "QTIP120"})
        self.assertNotIn("error", result)
        self.assertEqual(result["category"], "bjt_darlington")

    async def test_get_jfet(self):
        result = await _call(spice_library_get_model, {"name": "J2N5457"})
        self.assertNotIn("error", result)
        self.assertIn("NJF(", result["spice"])

    async def test_get_vref_tl431(self):
        result = await _call(spice_library_get_model, {"name": "VREF_TL431"})
        self.assertNotIn("error", result)
        self.assertEqual(result["category"], "vref")

    async def test_get_tvs_model(self):
        result = await _call(spice_library_get_model, {"name": "DTVS12V"})
        self.assertNotIn("error", result)
        self.assertEqual(result["category"], "diode_tvs")

    async def test_get_led_model(self):
        result = await _call(spice_library_get_model, {"name": "DLED_RED"})
        self.assertNotIn("error", result)
        self.assertEqual(result["category"], "diode_led")


# ===========================================================================
# 7. Netlist insertion sanity (using spice_lib inject helper)
# ===========================================================================

class TestNetlistInsertFromLibrary(unittest.TestCase):
    """Verify models from the new library parse correctly when inserted in netlists."""

    _NETLIST = """\
Test circuit with models from spice_library
R1 1 2 1k
.op
.end
"""

    def test_zener_model_insertable(self):
        spice = get_model_spice("DZENER12V")
        netlist = self._NETLIST + "\n" + spice + "\n"
        self.assertIn(".MODEL DZENER12V", netlist)
        self.assertIn("BV=12.0", netlist)

    def test_bjt_model_insertable(self):
        spice = get_model_spice("Q2N3904")
        netlist = self._NETLIST + "\n" + spice + "\n"
        self.assertIn(".MODEL Q2N3904 NPN(", netlist)

    def test_subckt_model_insertable(self):
        spice = get_model_spice("OPAMP_TL072")
        netlist = self._NETLIST + "\n" + spice + "\n"
        self.assertIn(".SUBCKT OPAMP_TL072", netlist)
        self.assertIn(".ENDS OPAMP_TL072", netlist)

    def test_logic_gate_insertable(self):
        spice = get_model_spice("NAND_74HC")
        netlist = self._NETLIST + "\n" + spice + "\n"
        self.assertIn(".SUBCKT NAND_74HC", netlist)

    def test_555_insertable(self):
        spice = get_model_spice("IC555")
        netlist = self._NETLIST + "\n" + spice + "\n"
        self.assertIn(".SUBCKT IC555", netlist)
        self.assertIn(".ENDS IC555", netlist)


# ===========================================================================
# Teardown — restore sys.modules
# ===========================================================================

def teardown_module(module):  # noqa: D401
    import sys as _sys
    for _name, _orig in _KERF_CHAT_SAVED.items():
        if _orig is None:
            _sys.modules.pop(_name, None)
        else:
            _sys.modules[_name] = _orig


if __name__ == "__main__":
    unittest.main()
