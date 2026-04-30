"""Agent 1: Context Builder.

Reads raw discharge text + SDOH responses → extracts clinical entities, classifies
SDOH risks, builds a NetworkX knowledge graph, computes a fused risk score,
and persists everything (clinical_data, sdoh_profiles, knowledge_graphs,
reasoning_traces).
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.state import PatientState
from app.db.client import safe_upsert, safe_insert
from app.tools import kg as kg_tools
from app.tools.llm import chat_json

log = logging.getLogger(__name__)

SEVERITY_BY_RISK = {"low": 0.2, "medium": 0.55, "high": 0.9}


def _aggregate_sdoh_score(profile: dict[str, Any]) -> float:
    dims = ("housing_risk", "transport_risk", "caregiver_risk", "literacy_level", "digital_comfort", "financial_risk")
    vals = [SEVERITY_BY_RISK.get((profile.get(d) or "low").lower(), 0.2) for d in dims]
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def _persist_reasoning_trace(
    patient_id: str, observed: dict, inferred: dict, decided: str, tools_called: list[str]
) -> None:
    safe_insert(
        "reasoning_traces",
        {
            "patient_id": patient_id,
            "agent_name": "context_builder",
            "observed": observed,
            "inferred": inferred,
            "decided": decided,
            "tools_called": tools_called,
        },
    )


def context_builder_node(state: PatientState) -> PatientState:
    patient_id = state["patient_id"]
    raw_text = state.get("raw_discharge_text", "")
    sdoh_responses = state.get("sdoh_responses", {})

    tools_called: list[str] = []

    # Step 1: extract clinical entities
    clinical = chat_json("clinical_ner", discharge_text=raw_text) or {}
    tools_called.append("llm:clinical_ner")
    log.info("Clinical extracted: %s", {k: clinical.get(k) for k in ("diagnosis", "icd_codes")})

    # Step 2: classify SDOH
    sdoh_profile = chat_json("sdoh_classifier", sdoh_responses=sdoh_responses) or {}
    tools_called.append("llm:sdoh_classifier")

    # Step 3: build KG
    g = kg_tools.build_patient_graph(clinical, sdoh_profile)
    g_json = kg_tools.graph_to_json(g)
    tools_called.append("kg:build")

    # Step 4: fused risk score
    clinical_severity = float(clinical.get("clinical_severity") or 0.6)
    sdoh_aggregate = float(sdoh_profile.get("sdoh_aggregate") or _aggregate_sdoh_score(sdoh_profile))
    risk_score = round(clinical_severity * 0.4 + sdoh_aggregate * 0.6, 3)

    # Step 5: persist
    safe_upsert(
        "clinical_data",
        {
            "patient_id": patient_id,
            "diagnosis": clinical.get("diagnosis"),
            "icd_codes": clinical.get("icd_codes") or [],
            "medications": clinical.get("medications") or [],
            "comorbidities": clinical.get("comorbidities") or [],
            "discharge_date": clinical.get("discharge_date"),
            "follow_up_date": clinical.get("follow_up_date"),
        },
        on_conflict="patient_id",
    )
    safe_upsert(
        "sdoh_profiles",
        {
            "patient_id": patient_id,
            "housing_risk": sdoh_profile.get("housing_risk"),
            "transport_risk": sdoh_profile.get("transport_risk"),
            "caregiver_risk": sdoh_profile.get("caregiver_risk"),
            "literacy_level": sdoh_profile.get("literacy_level"),
            "digital_comfort": sdoh_profile.get("digital_comfort"),
            "financial_risk": sdoh_profile.get("financial_risk"),
            "language": sdoh_profile.get("language") or state.get("language", "hi"),
        },
        on_conflict="patient_id",
    )
    safe_upsert(
        "knowledge_graphs",
        {"patient_id": patient_id, "graph_json": g_json},
        on_conflict="patient_id",
    )
    tools_called.append("db:upsert(clinical_data,sdoh_profiles,knowledge_graphs)")

    decided = (
        f"Built KG with {g.number_of_nodes()} nodes / {g.number_of_edges()} edges. "
        f"Fused risk score = {risk_score} (clinical={clinical_severity}, sdoh={sdoh_aggregate})."
    )

    _persist_reasoning_trace(
        patient_id=patient_id,
        observed={
            "discharge_text_length": len(raw_text),
            "sdoh_responses": sdoh_responses,
        },
        inferred={
            "clinical": clinical,
            "sdoh_profile": sdoh_profile,
            "kg_summary": kg_tools.kg_highlights(g),
            "risk_score": risk_score,
        },
        decided=decided,
        tools_called=tools_called,
    )

    state["clinical_extracted"] = clinical
    state["sdoh_profile"] = sdoh_profile
    state["knowledge_graph"] = g
    state["knowledge_graph_json"] = g_json
    state["risk_score"] = risk_score
    state["language"] = sdoh_profile.get("language") or state.get("language", "hi")
    state.setdefault("tools_called", []).extend(tools_called)
    state.setdefault("reasoning_steps", []).append(
        {
            "agent": "context_builder",
            "observed": {"sdoh_responses": sdoh_responses},
            "inferred": {"risk_score": risk_score, "diagnosis": clinical.get("diagnosis")},
            "decided": decided,
            "tools_called": tools_called,
        }
    )
    return state
