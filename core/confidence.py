"""
core/confidence.py

Calculates confidence scores (0-100) per risk by combining primary risk predictions
with secondary model crosscheck audits.
Disagreements significantly lower confidence. Risks below threshold (default: 50)
are explicitly flagged as "needs human review".
"""

from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class EvaluatedRisk:
    description: str
    affected_function: str
    severity: str
    reasoning: str
    confidence_score: int
    crosscheck_status: str  # agreed, disagreed, unverified
    crosscheck_note: str
    needs_human_review: bool
    status: str  # CONFIRMED RISK, NEEDS HUMAN REVIEW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "affected_function": self.affected_function,
            "severity": self.severity,
            "reasoning": self.reasoning,
            "confidence_score": self.confidence_score,
            "crosscheck_status": self.crosscheck_status,
            "crosscheck_note": self.crosscheck_note,
            "needs_human_review": self.needs_human_review,
            "status": self.status,
        }


def compute_confidence_scores(
    risks: List[Dict[str, Any]],
    checks: List[Dict[str, Any]],
    confidence_threshold: int = 50
) -> List[EvaluatedRisk]:
    """
    Combines risk predictions and crosscheck assessments into confidence-scored risk reports.
    """
    # Index checks by risk_index
    checks_by_idx: Dict[int, Dict[str, Any]] = {}
    for c in checks:
        idx = c.get("risk_index")
        if idx is not None:
            checks_by_idx[idx] = c

    evaluated_risks: List[EvaluatedRisk] = []

    for i, risk in enumerate(risks):
        sev = str(risk.get("severity", "medium")).lower()
        
        # Initial base confidence based on severity and reasoning detail
        if sev == "high":
            base_score = 85
        elif sev == "medium":
            base_score = 75
        else:
            base_score = 65

        check = checks_by_idx.get(i)
        
        if check is not None:
            agrees = check.get("agrees", False)
            note = check.get("note", "")
            if agrees:
                confidence_score = min(100, base_score + 10)
                crosscheck_status = "agreed"
            else:
                # Disagreement substantially lowers confidence!
                confidence_score = max(10, base_score - 45)
                crosscheck_status = "disagreed"
        else:
            crosscheck_status = "unverified"
            note = "No crosscheck model response available."
            confidence_score = max(20, base_score - 20)

        needs_review = confidence_score < confidence_threshold
        status_label = "NEEDS HUMAN REVIEW" if needs_review else "CONFIRMED RISK"

        evaluated_risks.append(
            EvaluatedRisk(
                description=str(risk.get("description", "")),
                affected_function=str(risk.get("affected_function", "")),
                severity=sev,
                reasoning=str(risk.get("reasoning", "")),
                confidence_score=confidence_score,
                crosscheck_status=crosscheck_status,
                crosscheck_note=note,
                needs_human_review=needs_review,
                status=status_label
            )
        )

    return evaluated_risks


if __name__ == "__main__":
    print("[+] Testing core/confidence.py standalone...")
    
    sample_risks = [
        {
            "description": "API break in process_data",
            "affected_function": "process_data",
            "severity": "high",
            "reasoning": "Default parameter changed."
        },
        {
            "description": "Hallucinated crash risk",
            "affected_function": "helper_func",
            "severity": "medium",
            "reasoning": "Claimed null pointer dereference."
        }
    ]

    sample_checks = [
        {
            "risk_index": 0,
            "agrees": True,
            "note": "Agreed: process_data caller expects 3 arguments."
        },
        {
            "risk_index": 1,
            "agrees": False,
            "note": "Disagreed: helper_func explicitly checks for null before dereference."
        }
    ]

    evaluated = compute_confidence_scores(sample_risks, sample_checks, confidence_threshold=50)
    print(f"[+] Evaluated {len(evaluated)} risks:")
    for r in evaluated:
        print(f"  - {r.description}: Score={r.confidence_score}, Status={r.status}, Crosscheck={r.crosscheck_status}")
    
    assert evaluated[0].confidence_score >= 50
    assert evaluated[0].needs_human_review == False
    assert evaluated[1].confidence_score < 50
    assert evaluated[1].needs_human_review == True

    print("[+] core/confidence.py tests completed successfully!")
