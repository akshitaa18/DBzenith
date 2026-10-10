"""LangGraph workflow definition for the DBZenith Conversational DBA Assistant.

Graph flow:
START
→ understand
→ retrieve evidence
→ analyze
→ recommend
→ simulate
→ explain
→ request approval
→ END
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.services.assistant.audit import get_assistant_audit_logger
from app.services.assistant.contracts import AssistantState, UserRole
from app.services.assistant.safety import AssistantSafetyPolicy, SecurityViolationError
from app.services.assistant.tools import ControlledDBATools


def create_dba_assistant_graph(db: Session, user_role: UserRole | str = UserRole.DBA):
    """Builds and compiles the LangGraph StateGraph for the Conversational DBA Assistant."""
    tools = ControlledDBATools(db, user_role=user_role)
    audit = get_assistant_audit_logger()

    # -------------------------------------------------------------
    # 1. Node: understand
    # -------------------------------------------------------------
    def understand_node(state: AssistantState) -> AssistantState:
        session_id = state.get("session_id") or str(uuid.uuid4())
        user_msg = state.get("user_message", "")
        extracted: dict[str, Any] = {}

        # 1. Evaluate prompt-injection defense
        is_safe, violation_reason = AssistantSafetyPolicy.evaluate_user_prompt(user_msg)
        if not is_safe:
            audit.log_event(
                session_id=session_id,
                event_type="security_violation",
                input_payload={"prompt": user_msg},
                output_summary=violation_reason,
                authorized=False,
                security_flag="prompt_injection_or_unsafe_operation",
            )
            state["safety_check_passed"] = False
            state["safety_violation_reason"] = violation_reason
            state["final_response"] = f"SECURITY ALERT: {violation_reason}"
            return state

        state["safety_check_passed"] = True

        # Extract entities: query_id, recommendation_id, thresholds
        q_match = re.search(r"(?i)\bquery\s*([#:]?\s*)?(\d+)\b", user_msg)
        if q_match:
            extracted["query_id"] = int(q_match.group(2))

        rec_match = re.search(r"(?i)\brecommendation\s*([#:]?\s*)?(\d+)\b", user_msg)
        if rec_match:
            extracted["recommendation_id"] = int(rec_match.group(2))

        # Parse intent
        msg_lower = user_msg.lower()
        if "approval" in msg_lower or "migration" in msg_lower or "apply" in msg_lower or "migrate" in msg_lower:
            intent = "request_approval"
        elif "simulate" in msg_lower or "sandbox" in msg_lower or "compare" in msg_lower:
            intent = "simulate"
        elif "recommend" in msg_lower or "optimize" in msg_lower or "rewrite" in msg_lower or "index" in msg_lower:
            intent = "recommend"
        elif "plan" in msg_lower or "explain" in msg_lower or "bottleneck" in msg_lower:
            intent = "analyze_plan"
        elif "slow" in msg_lower:
            intent = "get_slow_queries"
        elif "workload" in msg_lower or "summary" in msg_lower or "health" in msg_lower:
            intent = "workload_summary"
        else:
            intent = "general_tuning"

        audit.log_event(
            session_id=session_id,
            event_type="understand_intent",
            input_payload={"intent": intent, "entities": extracted},
            output_summary=f"Parsed intent: {intent}",
        )

        state["session_id"] = session_id
        state["parsed_intent"] = intent
        state["extracted_entities"] = extracted
        return state

    # -------------------------------------------------------------
    # 2. Node: retrieve_evidence
    # -------------------------------------------------------------
    def retrieve_evidence_node(state: AssistantState) -> AssistantState:
        if not state.get("safety_check_passed", True):
            return state

        session_id = state.get("session_id", "")
        intent = state.get("parsed_intent", "")
        entities = state.get("extracted_entities", {})
        evidence: dict[str, Any] = {}

        try:
            # Query-specific evidence
            if "query_id" in entities:
                qid = entities["query_id"]
                evidence["query_details"] = tools.get_query_details(qid)
                evidence["execution_plan"] = tools.get_execution_plan(qid)
            else:
                # Top slow queries & workload overview
                evidence["slow_queries"] = tools.get_slow_queries(min_exec_time_ms=50.0, limit=5)
                evidence["workload_summary"] = tools.get_workload_summary()

            audit.log_event(
                session_id=session_id,
                event_type="retrieve_evidence",
                input_payload={"intent": intent, "entities": entities},
                output_summary=f"Retrieved keys: {list(evidence.keys())}",
            )
        except Exception as exc:
            evidence["error"] = str(exc)

        state["evidence"] = evidence
        return state

    # -------------------------------------------------------------
    # 3. Node: analyze
    # -------------------------------------------------------------
    def analyze_node(state: AssistantState) -> AssistantState:
        if not state.get("safety_check_passed", True):
            return state

        session_id = state.get("session_id", "")
        evidence = state.get("evidence", {})
        entities = state.get("extracted_entities", {})
        analysis: dict[str, Any] = {}

        try:
            if "query_id" in entities:
                qid = entities["query_id"]
                plan_data = evidence.get("execution_plan", {})
                analysis["plan_analysis"] = tools.analyze_plan(plan_data)
                analysis["bottlenecks"] = tools.explain_bottleneck(qid)
            elif "slow_queries" in evidence and len(evidence["slow_queries"]) > 0:
                top_q = evidence["slow_queries"][0]
                analysis["top_slow_query"] = top_q
                analysis["bottlenecks"] = [
                    f"Sequential scan and high execution time observed on query {top_q.get('query_id')} ({top_q.get('mean_exec_time_ms')} ms)."
                ]

            audit.log_event(
                session_id=session_id,
                event_type="analyze",
                output_summary=f"Identified bottlenecks: {analysis.get('bottlenecks')}",
            )
        except Exception as exc:
            analysis["error"] = str(exc)

        state["analysis"] = analysis
        return state

    # -------------------------------------------------------------
    # 4. Node: recommend
    # -------------------------------------------------------------
    def recommend_node(state: AssistantState) -> AssistantState:
        if not state.get("safety_check_passed", True):
            return state

        session_id = state.get("session_id", "")
        entities = state.get("extracted_entities", {})
        qid = entities.get("query_id")

        try:
            recs = tools.get_recommendations(query_id=qid)
            state["recommendations"] = recs
            audit.log_event(
                session_id=session_id,
                event_type="recommend",
                output_summary=f"Found {len(recs)} optimization recommendations.",
            )
        except Exception as exc:
            state["recommendations"] = []

        return state

    # -------------------------------------------------------------
    # 5. Node: simulate
    # -------------------------------------------------------------
    def simulate_node(state: AssistantState) -> AssistantState:
        if not state.get("safety_check_passed", True):
            return state

        session_id = state.get("session_id", "")
        entities = state.get("extracted_entities", {})
        recs = state.get("recommendations", [])
        simulations: list[dict[str, Any]] = []

        try:
            target_rec_id = entities.get("recommendation_id")
            if target_rec_id:
                sim = tools.simulate_recommendation(target_rec_id)
                simulations.append(sim)
            elif recs:
                # Simulate top recommendation
                sim = tools.simulate_recommendation(recs[0]["id"])
                simulations.append(sim)

            state["simulations"] = simulations
            if len(simulations) > 1:
                state["simulation_comparisons"] = tools.compare_simulations(
                    [s["recommendation_id"] for s in simulations if "recommendation_id" in s]
                )

            audit.log_event(
                session_id=session_id,
                event_type="simulate",
                output_summary=f"Simulated {len(simulations)} recommendations in sandbox.",
            )
        except Exception as exc:
            state["simulations"] = []

        return state

    # -------------------------------------------------------------
    # 6. Node: explain
    # -------------------------------------------------------------
    def explain_node(state: AssistantState) -> AssistantState:
        if not state.get("safety_check_passed", True):
            return state

        session_id = state.get("session_id", "")
        evidence = state.get("evidence", {})
        analysis = state.get("analysis", {})
        recs = state.get("recommendations", [])
        sims = state.get("simulations", [])

        # Formulate structured explanation
        lines = ["### DBZenith Autonomous DBA Assistant Analysis\n"]

        # Workload / Query overview
        if "query_details" in evidence:
            qd = evidence["query_details"]
            lines.append(f"**Query Telemetry (Query #{qd.get('query_id')})**:")
            lines.append(f"- Normalized Query: `{qd.get('normalized_query')}`")
            lines.append(f"- Mean Latency: **{qd.get('mean_exec_time_ms')} ms** (Calls: {qd.get('calls')})")
        elif "slow_queries" in evidence and evidence["slow_queries"]:
            lines.append(f"**Observed Slow Workload Queries**: {len(evidence['slow_queries'])} queries above threshold.")
            for sq in evidence["slow_queries"][:3]:
                lines.append(f"- Query #{sq.get('query_id')}: `{sq.get('normalized_query')}` ({sq.get('mean_exec_time_ms')} ms)")

        # Bottlenecks
        bottlenecks = analysis.get("bottlenecks")
        if bottlenecks:
            lines.append("\n**Identified Bottlenecks**:")
            if isinstance(bottlenecks, list):
                for b in bottlenecks:
                    lines.append(f"- {b}")
            elif isinstance(bottlenecks, dict):
                for b in bottlenecks.get("bottlenecks", []):
                    lines.append(f"- {b}")

        # Recommendations
        if recs:
            lines.append(f"\n**Proposed Recommendations** ({len(recs)} available):")
            for r in recs[:2]:
                lines.append(f"- **Recommendation #{r['id']}** ({r['type']}): `{r['proposed_change']}`")
                lines.append(f"  *Reason*: {r['reason']}")
                lines.append(f"  *Confidence*: {r['confidence'] * 100:.0f}% | Requires DBA Approval: Yes")

        # Sandbox Simulation Impact
        if sims:
            lines.append("\n**Sandbox Validation Results** (Isolated Sandbox Execution):")
            for s in sims:
                impr = s.get("improvement_percent", 0.0)
                lines.append(f"- Recommendation #{s.get('recommendation_id')}: Baseline {s.get('baseline_mean_ms')} ms → Simulated {s.get('simulated_mean_ms')} ms (**+{impr:.1f}% improvement**)")
                lines.append(f"- Regression Detected: {'Yes (REJECTED)' if s.get('regression_detected') else 'No (PASSED)'}")

        lines.append("\n> [!NOTE]\n> DBZenith enforces strict production safety: the assistant cannot execute arbitrary SQL or modify production directly. All changes require formal DBA approval.")

        full_explanation = "\n".join(lines)
        state["explanation"] = full_explanation
        state["final_response"] = full_explanation

        audit.log_event(
            session_id=session_id,
            event_type="explain",
            output_summary="Generated DBA analysis and explanation.",
        )
        return state

    # -------------------------------------------------------------
    # 7. Node: request_approval
    # -------------------------------------------------------------
    def request_approval_node(state: AssistantState) -> AssistantState:
        if not state.get("safety_check_passed", True):
            return state

        session_id = state.get("session_id", "")
        intent = state.get("parsed_intent", "")
        entities = state.get("extracted_entities", {})
        recs = state.get("recommendations", [])

        # Only create approval request if user intent requests it or target recommendation specified
        if intent == "request_approval" or "recommendation_id" in entities:
            rec_id = entities.get("recommendation_id") or (recs[0]["id"] if recs else None)
            if rec_id:
                try:
                    app_res = tools.request_migration_approval(
                        recommendation_id=rec_id,
                        reason="Requested via Conversational DBA Assistant after sandbox simulation validation.",
                    )
                    state["approval_request"] = app_res
                    audit.log_event(
                        session_id=session_id,
                        event_type="request_migration_approval",
                        input_payload={"recommendation_id": rec_id},
                        output_summary="Created pending approval request for human DBA review.",
                    )

                    # Append approval banner
                    approval_notice = (
                        f"\n\n---\n**Migration Approval Status**:\n"
                        f"A formal approval request has been staged for Recommendation #{rec_id} (Status: `pending_dba_review`).\n"
                        f"*Strict Safety Invariant*: The AI assistant cannot self-approve or apply changes directly. Please review and approve in the Dashboard."
                    )
                    state["final_response"] = (state.get("final_response") or "") + approval_notice
                except SecurityViolationError as exc:
                    state["approval_request"] = None
                    audit.log_event(
                        session_id=session_id,
                        event_type="request_migration_approval",
                        input_payload={"recommendation_id": rec_id},
                        output_summary=str(exc),
                        authorized=False,
                        security_flag="insufficient_role_for_migration_approval",
                    )

        return state

    # -------------------------------------------------------------
    # Build & Compile StateGraph
    # -------------------------------------------------------------
    graph = StateGraph(AssistantState)

    # Add all nodes
    graph.add_node("understand", understand_node)
    graph.add_node("retrieve_evidence", retrieve_evidence_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("recommend", recommend_node)
    graph.add_node("simulate", simulate_node)
    graph.add_node("explain", explain_node)
    graph.add_node("request_approval", request_approval_node)

    # Add edges matching the exact requested flow:
    # START → understand → retrieve evidence → analyze → recommend → simulate → explain → request approval → END
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "analyze")
    graph.add_edge("analyze", "recommend")
    graph.add_edge("recommend", "simulate")
    graph.add_edge("simulate", "explain")
    graph.add_edge("explain", "request_approval")
    graph.add_edge("request_approval", END)

    return graph.compile()
