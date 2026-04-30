"""LangGraph orchestrator: stitches the four agent nodes together.

We expose two flows:
- onboarding_flow(state): context_builder → care_plan
- engagement_flow(state):  engagement (which may invoke pharmacy internally)

The graph is intentionally simple — autonomy lives inside each node, not in the
edge structure. Adding LangGraph here keeps us aligned with the spec and lets
us add conditional edges later (e.g. router based on severity).
"""
from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.agents.care_plan import care_plan_node
from app.agents.context_builder import context_builder_node
from app.agents.engagement import engagement_node
from app.agents.pharmacy import pharmacy_node
from app.agents.state import PatientState

log = logging.getLogger(__name__)


def _build_onboarding_graph():
    g = StateGraph(PatientState)
    g.add_node("ctx_builder_node", context_builder_node)
    g.add_node("care_plan_node", care_plan_node)
    g.set_entry_point("ctx_builder_node")
    g.add_edge("ctx_builder_node", "care_plan_node")
    g.add_edge("care_plan_node", END)
    return g.compile()


def _build_engagement_graph():
    g = StateGraph(PatientState)
    g.add_node("engagement_node", engagement_node)
    g.set_entry_point("engagement_node")
    g.add_edge("engagement_node", END)
    return g.compile()


def _build_pharmacy_graph():
    g = StateGraph(PatientState)
    g.add_node("pharmacy_node", pharmacy_node)
    g.set_entry_point("pharmacy_node")
    g.add_edge("pharmacy_node", END)
    return g.compile()


_onboarding = _build_onboarding_graph()
_engagement = _build_engagement_graph()
_pharmacy = _build_pharmacy_graph()


def run_onboarding(state: PatientState) -> PatientState:
    log.info("Running onboarding flow for patient %s", state.get("patient_id"))
    return _onboarding.invoke(state)


def run_engagement(state: PatientState) -> PatientState:
    log.info("Running engagement flow for patient %s", state.get("patient_id"))
    return _engagement.invoke(state)


def run_pharmacy(state: PatientState) -> PatientState:
    log.info("Running pharmacy flow for patient %s", state.get("patient_id"))
    return _pharmacy.invoke(state)
