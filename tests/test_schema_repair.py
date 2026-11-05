"""Models often return text fields as lists of steps; schemas must coerce, not fail."""
from backend.models import StrategyCard, ASearcherAnalysis
from backend.client import ModelClient


RAW_EXPLORER = {
    "analysis": {
        "available_info": ["Given: unit-distance graph", "Target: subpolynomial bound"],
        "plan": "Form unit-distance graph, then count edges.",
        "uncertainties": "Boundary case n=1",
    },
    "normalized_problem": "Prove the unit-distance bound.",
    "primary_route": [
        "Step 1: Form unit-distance graph on the point set.",
        "Step 2: Bound edges using incidence estimates growing subpolynomially.",
    ],
    "backup_routes": "Induction on the number of points",
    "first_hard_obstruction": ["Incidence bound is tight only for large n"],
    "active_obligations": "Verify the base case",
    "risky_lemmas": [{"lemma": "Incidence bound"}, "Edge-count lemma"],
    "concrete_next_task": "Decompose into graph construction and counting.",
    "readiness_assessment": "Ready",
}


def test_strategy_card_coerces_list_primary_route():
    card = StrategyCard.model_validate(RAW_EXPLORER)
    assert isinstance(card.primary_route, str)
    assert "Step 1: Form unit-distance graph" in card.primary_route
    assert "Step 2: Bound edges" in card.primary_route
    assert card.backup_routes == ["Induction on the number of points"]
    assert card.active_obligations == ["Verify the base case"]
    assert card.first_hard_obstruction.startswith("Incidence bound")
    assert all(isinstance(x, str) for x in card.risky_lemmas)


def test_client_schema_validation_repairs_list_route():
    client = ModelClient(api_key="test-meta", mock_mode=True)
    repaired = client._validate_or_repair_schema(dict(RAW_EXPLORER), StrategyCard, "explorer", raw_text="{}")
    assert "Step 1: Form unit-distance graph" in repaired["primary_route"]


def test_enum_values_are_normalized_case_insensitively():
    from backend.models import (
        VerificationReport, FalsifierReport, SectionSolution,
        GateDecision, SectionReview, GlobalVerdict, Defect,
    )
    assert VerificationReport.model_validate({"verdict": "REJECT"}).verdict == "rejected"
    assert VerificationReport.model_validate({"verdict": "ACCEPT"}).verdict == "accepted"
    assert VerificationReport.model_validate({"verdict": "Conditional"}).verdict == "conditional"
    assert FalsifierReport.model_validate({"verdict": "SURVIVES"}).verdict == "survives"
    assert FalsifierReport.model_validate({"verdict": "Needs Repair"}).verdict == "needs_repair"
    assert SectionSolution.model_validate({"status": "SOLVED"}).status == "solved"
    assert GateDecision.model_validate({"decision": "READY"}).decision == "ready"
    assert GateDecision.model_validate({"decision": "Rejected"}).decision == "reject"
    assert SectionReview.model_validate({"verdict": "REJECT"}).verdict == "rejected"
    assert GlobalVerdict.model_validate({"verdict": "REJECTED", "next_action": "Revise"}).verdict == "reject"
    assert GlobalVerdict.model_validate({"verdict": "REJECTED", "next_action": "Revise"}).next_action == "revise"
    assert Defect.model_validate({"severity": "FATAL"}).severity == "fatal"


def test_client_repairs_uppercase_verdict():
    client = ModelClient(api_key="test-meta", mock_mode=True)
    from backend.models import VerificationReport
    repaired = client._validate_or_repair_schema({"verdict": "REJECT", "defects": []}, VerificationReport, "global_verifier", raw_text="{}")
    assert repaired["verdict"] == "rejected"


def test_raw_prose_is_preserved_not_emptied():
    client = ModelClient(api_key="test-meta", mock_mode=True)
    repaired = client._validate_or_repair_schema(
        {"raw": "Step 1: Form the unit-distance graph. Step 2: Count edges."},
        StrategyCard, "explorer", raw_text="Step 1: Form the unit-distance graph.",
    )
    assert "unit-distance graph" in repaired["primary_route"]


def test_wrapped_raw_route_and_string_analysis_are_unwrapped():
    card = StrategyCard.model_validate({
        "analysis": "Work in the unit-distance graph and count edges.",
        "primary_route": {"raw": "Step 1: Form the unit-distance graph. Step 2: Count edges."},
        "normalized_problem": "Bound u(n).",
    })
    assert isinstance(card.primary_route, str)
    assert "unit-distance graph" in card.primary_route
    assert card.analysis is not None
    assert "unit-distance graph" in (card.analysis.plan or card.analysis.available_info)


def test_list_of_dict_fields_accept_single_sentence():
    card = StrategyCard.model_validate({
        "primary_route": "Count unit pairs via incidences.",
        "preserved_critiques": "Do not claim exact formulas or count ordered pairs separately.",
    })
    assert card.preserved_critiques == [
        {"claim": "Do not claim exact formulas or count ordered pairs separately."}
    ]


def test_section_plan_accepts_alternate_shapes():
    from backend.models import SectionPlan
    plan = SectionPlan.model_validate({
        "sections": [
            {"title": "Upper bound", "claim": "Prove U(P) <= C n^{4/3} via incidences."},
            {"name": "Lower bound", "target": "Give a lattice construction.", "dependencies": [1]},
        ]
    })
    assert len(plan.subproblems) == 2
    assert plan.subproblems[0].id == "SEC_1"
    assert plan.subproblems[0].index == 1
    assert "incidences" in plan.subproblems[0].target_claim
    assert plan.subproblems[1].dependencies == [1]

    plan2 = SectionPlan.model_validate({
        "subproblems": [{"index": 1, "title": "Setup", "target_claim": "Define U(P)."}]
    })
    assert plan2.subproblems[0].id == "SEC_1"


def test_wrapped_plan_is_not_masked_as_empty():
    from backend.models import SectionPlan
    client = ModelClient(api_key="test-meta", mock_mode=True)
    repaired = client._validate_or_repair_schema(
        {"plan": {"subproblems": [{"index": 1, "title": "Upper bound", "target_claim": "Prove the incidence bound."}], "latex_skeleton": "x"}},
        SectionPlan, "decomposer", raw_text="{}",
    )
    assert len(repaired["subproblems"]) == 1
    assert repaired["subproblems"][0]["title"] == "Upper bound"


def test_falsifier_objections_accept_plain_sentences():
    from backend.models import FalsifierReport
    report = FalsifierReport.model_validate({
        "verdict": "needs_repair",
        "objections": ["O1: The incidence step assumes distinct points.", "O2: Boundary case n=1 is ignored."],
        "categorized_objections": ["Counting may double-count ordered pairs."],
    })
    assert report.verdict == "needs_repair"
    assert len(report.objections) == 2
    assert len(report.categorized_objections) == 1


def test_analysis_coerces_list_text():
    analysis = ASearcherAnalysis.model_validate(RAW_EXPLORER["analysis"])
    assert "unit-distance graph" in analysis.available_info
    assert analysis.uncertainties == ["Boundary case n=1"]
