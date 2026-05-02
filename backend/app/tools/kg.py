"""NetworkX knowledge graph builder + query helpers.

The KG fuses clinical entities (diagnosis, medications, comorbidities) with
SDOH dimensions and routes (channel, escalation paths). Edges carry weights
that the LLM uses as context when authoring care plans.
"""
from __future__ import annotations

import json
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph


# Domain rules linking SDOH risk to channel / cadence / caregiver loop
SDOH_TO_ROUTE_RULES = [
    # (predicate(profile_dict) -> bool, target_node, weight, label)
    (lambda p: p.get("digital_comfort") == "low", "channel:whatsapp_voice", 0.9, "needs_voice"),
    (lambda p: p.get("digital_comfort") == "high", "channel:whatsapp_text", 0.7, "text_ok"),
    (lambda p: p.get("literacy_level") == "low", "simplification:high", 0.9, "low_literacy"),
    (lambda p: p.get("literacy_level") == "low", "channel:whatsapp_voice", 0.6, "voice_for_literacy"),
    (lambda p: p.get("caregiver_risk") == "high", "caregiver_loop:enabled", 0.9, "lives_alone"),
    (lambda p: p.get("transport_risk") == "high", "telehealth:preferred", 0.8, "no_transport"),
    (lambda p: p.get("financial_risk") == "high", "telehealth:preferred", 0.85, "low_income"),
]

# Diagnosis-specific red flags
DIAGNOSIS_RED_FLAGS: dict[str, list[str]] = {
    "chf": [
        "weight gain >2kg in 3 days",
        "shortness of breath at rest",
        "ankle swelling",
        "orthopnea",
        "wet cough at night",
    ],
    "heart failure": [
        "weight gain >2kg in 3 days",
        "shortness of breath at rest",
        "ankle swelling",
        "orthopnea",
    ],
    "copd": ["increased sputum", "fever >38C", "severe shortness of breath", "blue lips"],
    "diabetes": ["very high or low blood sugar", "confusion", "frequent vomiting", "rapid breathing"],
    "post-mi": ["chest pain", "left arm pain", "pressure in chest", "fainting"],
    "cabg": ["chest wound redness", "fever", "chest pain", "shortness of breath"],
}


def diagnosis_red_flags(diagnosis: str) -> list[str]:
    if not diagnosis:
        return []
    d = diagnosis.lower()
    for key, flags in DIAGNOSIS_RED_FLAGS.items():
        if key in d:
            return flags
    return []


def build_patient_graph(
    clinical: dict[str, Any], sdoh_profile: dict[str, Any]
) -> nx.DiGraph:
    """Construct the patient KG. Returns a DiGraph with weighted edges."""
    g: nx.DiGraph = nx.DiGraph()

    # Nodes: diagnosis + comorbidities
    diagnosis = (clinical.get("diagnosis") or "").strip()
    if diagnosis:
        g.add_node(f"dx:{diagnosis}", kind="diagnosis", label=diagnosis)
    for c in clinical.get("comorbidities") or []:
        if c:
            g.add_node(f"comorb:{c}", kind="comorbidity", label=c)
            if diagnosis:
                g.add_edge(f"dx:{diagnosis}", f"comorb:{c}", weight=0.4, label="comorbid_with")

    # Nodes: medications
    for med in clinical.get("medications") or []:
        name = (med.get("name") or "").strip() if isinstance(med, dict) else str(med)
        if not name:
            continue
        g.add_node(f"med:{name}", kind="medication", label=name, **(med if isinstance(med, dict) else {}))
        if diagnosis:
            g.add_edge(f"dx:{diagnosis}", f"med:{name}", weight=0.6, label="treated_with")

    # Nodes: SDOH dimensions
    for dim in (
        "housing_risk",
        "transport_risk",
        "caregiver_risk",
        "literacy_level",
        "digital_comfort",
        "financial_risk",
    ):
        risk = sdoh_profile.get(dim)
        if risk:
            node = f"sdoh:{dim}={risk}"
            g.add_node(node, kind="sdoh", dimension=dim, risk=risk, label=f"{dim}: {risk}")

    # Nodes: red flags
    for flag in diagnosis_red_flags(diagnosis):
        node = f"flag:{flag}"
        g.add_node(node, kind="red_flag", label=flag)
        if diagnosis:
            g.add_edge(f"dx:{diagnosis}", node, weight=0.95, label="watch_for")

    # Routing nodes (decision targets)
    for n in [
        "channel:whatsapp_text",
        "channel:whatsapp_voice",
        "channel:voice_call",
        "simplification:high",
        "simplification:medium",
        "caregiver_loop:enabled",
        "telehealth:preferred",
    ]:
        g.add_node(n, kind="route", label=n)

    # Apply SDOH→route weighted edges
    for predicate, target, weight, label in SDOH_TO_ROUTE_RULES:
        try:
            if predicate(sdoh_profile):
                # Find which sdoh node fired this rule
                for sdoh_node in [n for n in g.nodes if n.startswith("sdoh:")]:
                    g.add_edge(sdoh_node, target, weight=weight, label=label)
        except Exception:
            continue

    return g


def graph_to_json(g: nx.DiGraph) -> dict[str, Any]:
    """Serialize for storage / frontend (react-force-graph-2d format)."""
    try:
        raw = json_graph.node_link_data(g, edges="edges")
    except TypeError:
        raw = json_graph.node_link_data(g)
    edges_key = "edges" if "edges" in raw else "links"
    nodes = [
        {
            "id": n["id"],
            "label": n.get("label", n["id"]),
            "kind": n.get("kind", "other"),
            **{k: v for k, v in n.items() if k not in ("id", "label", "kind")},
        }
        for n in raw.get("nodes", [])
    ]
    links = [
        {
            "source": e["source"],
            "target": e["target"],
            "weight": e.get("weight", 0.5),
            "label": e.get("label", ""),
        }
        for e in raw.get(edges_key, [])
    ]
    return {"nodes": nodes, "links": links}


def graph_from_json(data: dict[str, Any]) -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    for n in data.get("nodes", []):
        g.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
    for e in data.get("links", []) or data.get("edges", []):
        g.add_edge(e["source"], e["target"], **{k: v for k, v in e.items() if k not in ("source", "target")})
    return g


def kg_highlights(g: nx.DiGraph) -> dict[str, Any]:
    """Pull a few high-signal facts for prompt context."""
    high_risk_sdoh = [
        n[len("sdoh:"):]
        for n in g.nodes
        if n.startswith("sdoh:") and ("=high" in n or "=low" in n)
    ]
    red_flags = [g.nodes[n].get("label") for n in g.nodes if n.startswith("flag:")]
    routes = [n for n in g.nodes if n.startswith("channel:") and g.in_degree(n) > 0]
    return {
        "high_risk_sdoh": high_risk_sdoh,
        "red_flags": red_flags,
        "preferred_routes": routes,
        "node_count": g.number_of_nodes(),
        "edge_count": g.number_of_edges(),
    }
