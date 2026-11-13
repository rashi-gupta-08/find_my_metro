"""The patent's context router (106) and independently replaceable engines (108–114)."""
from dataclasses import dataclass
from .config import settings
from .db import iso, parse
from .network import context_at


class ContextDeterminationEngine:
    reference = 108

    def determine(self, line_id, direction, accepted_position):
        return context_at(line_id, direction, accepted_position)


class DynamicTrustEngine:
    reference = 110

    def score(self, source, context, age):
        # Qualification, device health, route proximity and independent consensus are checked first.
        base = {"wsn": {"underground": .98, "transition": .94, "surface": .80},
                "crowd": {"underground": .70, "transition": .89, "surface": .96}}[source][context]
        maximum_age = settings.sensor_max_age_seconds if source == "wsn" else settings.crowd_max_age_seconds
        penalty = .25 if source == "wsn" else .30
        return round(max(0, min(.99, base-penalty*max(0, age)/maximum_age)), 3)


class BackendSwitchingEngine:
    reference = 112

    def select(self, state, candidates, scores, now):
        context=state.get("detected_context",state["context"])
        preferred = "wsn" if context == "underground" else "crowd" if context == "surface" else None
        winner = max(candidates, key=lambda source: scores[source]+(.08 if source == preferred else 0), default=None)
        reason = "no_qualified_evidence"
        active = state["source"] if state["source"] in candidates else None
        if winner and context!=state["context"]:
            # A qualified observation at a new zone must be able to initiate handover.
            reason="qualified_context_change"
            state["candidate"],state["candidate_count"]=None,0
        elif winner and active and winner != active:
            held = not state.get("last_switched_at") or (now-parse(state["last_switched_at"])).total_seconds() >= settings.switch_hold_seconds
            if scores[winner]-scores[active] <= settings.switch_margin:
                winner, reason = active, "switch_margin_not_met"
                state["candidate"], state["candidate_count"] = None, 0
            else:
                second = iso(now.replace(microsecond=0))
                if state.get("candidate") == winner:
                    if state.get("candidate_evaluated_at") != second:
                        state["candidate_count"] = state.get("candidate_count", 0)+1
                else:
                    state["candidate"], state["candidate_count"] = winner, 1
                state["candidate_evaluated_at"] = second
                if not held or state["candidate_count"] < settings.switch_confirmations:
                    winner, reason = active, "switch_confirmation_or_hold"
        elif winner:
            state["candidate"], state["candidate_count"] = None, 0
        return winner, reason, preferred


@dataclass
class ArbitrationResult:
    winner: str | None
    candidates: dict
    reason: str
    estimate: dict


class TransitionArbitrationEngine:
    reference = 114

    def estimate(self, snapshot, now):
        elapsed = max(0, (now-parse(snapshot["observed_at"])).total_seconds())
        started = parse(snapshot["started_at"])
        horizon = max(1, (parse(snapshot["deadline"])-started).total_seconds())
        age_in_window = max(0, (now-started).total_seconds())
        return {"position_m": min(snapshot["next_station_position_m"], snapshot["position_m"]+(snapshot.get("speed_mps") or 0)*elapsed),
                "trust": max(0, snapshot["trust"]*(1-age_in_window/horizon)),
                "expired": now >= parse(snapshot["deadline"])}

    def arbitrate(self, snapshot, candidates, scores, now):
        estimate = self.estimate(snapshot, now)
        fresh = {source: value for source, value in candidates.items() if parse(value["observed_at"]) > parse(snapshot["observed_at"])}
        reason = "transition_bounded_estimate"
        if "wsn" in fresh and "crowd" in fresh:
            sensor, crowd = fresh["wsn"], fresh["crowd"]
            matching = sensor.get("match_key") and sensor.get("match_key") == crowd.get("match_key") and sensor["kind"] == crowd["kind"]
            if matching and abs((parse(sensor["observed_at"])-parse(crowd["observed_at"])).total_seconds()) <= 45 and abs(sensor["position_m"]-crowd["position_m"]) <= 200:
                fresh["fused"] = {**max([sensor,crowd], key=lambda item:item["observed_at"]),
                                  "position_m": (sensor["position_m"]+crowd["position_m"])/2,
                                  "event_ids": sensor["event_ids"]+crowd["event_ids"]}
                scores["fused"] = min(.99, max(scores["wsn"],scores["crowd"])+.02)
                reason = "matching_evidence_fused"
            else:
                reason = "conflict_resolved_by_trust"
        # Claim 1: explicitly compare the incoming trust with the decaying position estimate.
        qualified = {source:value for source,value in fresh.items()
                     if scores[source] >= settings.min_source_trust and (estimate["expired"] or scores[source] > estimate["trust"])}
        winner = max(qualified, key=lambda source:scores[source], default=None)
        if not winner:
            reason = "transition_deadline_fallback" if estimate["expired"] else "incoming_below_estimate_trust" if fresh else "transition_bounded_estimate"
        elif reason == "transition_bounded_estimate":
            reason = "incoming_trust_exceeds_estimate"
        return ArbitrationResult(winner, fresh, reason, estimate)


class ContextAwareDataSourceRouter:
    reference = 106

    def __init__(self):
        self.context = ContextDeterminationEngine()
        self.trust = DynamicTrustEngine()
        self.switching = BackendSwitchingEngine()
        self.transition = TransitionArbitrationEngine()

    def select(self, state, candidates, scores, now):
        winner, reason, preferred = self.switching.select(state, candidates, scores, now)
        if state["context"] == "transition" and state.get("transition"):
            result = self.transition.arbitrate(state["transition"], candidates, scores, now)
            state["arbitration"] = {"estimated_trust": round(result.estimate["trust"],3),
                                    "incoming_trust": {source:scores[source] for source in result.candidates},
                                    "winner": result.winner, "reason": result.reason}
            if not result.winner:
                state.update(position_m=result.estimate["position_m"], trust=result.estimate["trust"],
                             freshness="schedule_fallback" if result.estimate["expired"] else "estimated")
            return result.winner, result.reason, preferred, result.candidates
        state["arbitration"] = None
        return winner, reason, preferred, candidates


router = ContextAwareDataSourceRouter()
