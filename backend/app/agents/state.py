from __future__ import annotations

from typing import Any, TypedDict


class ReasoningStep(TypedDict, total=False):
    agent: str
    observed: dict[str, Any]
    inferred: dict[str, Any]
    decided: str
    tools_called: list[str]


class PatientState(TypedDict, total=False):
    patient_id: str
    raw_discharge_text: str
    sdoh_responses: dict[str, Any]
    clinical_extracted: dict[str, Any]
    sdoh_profile: dict[str, Any]
    knowledge_graph: Any
    knowledge_graph_json: dict[str, Any]
    care_plan: dict[str, Any]
    current_message: str
    classification: dict[str, Any]
    decision: str
    tools_called: list[str]
    reasoning_steps: list[ReasoningStep]
    risk_score: float
    language: str
    channel: str
    patient_record: dict[str, Any]
    check_in_times_per_day: int
    triggered_by: str
    outgoing_messages: list[dict[str, Any]]
    outgoing_emails: list[dict[str, Any]]


def empty_state() -> PatientState:
    return PatientState(
        tools_called=[],
        reasoning_steps=[],
        risk_score=0.0,
        language="en",
        channel="whatsapp_text",
        outgoing_messages=[],
        outgoing_emails=[],
    )
