from typing import Dict, Any
from personalization.learnova_scoring import score_user
from personalization.scoring_config import TRACK_LABELS


def generate_routing_response(raw_payload: Dict[str, Any], weights_path: str = "track_weights.csv") -> Dict[str, Any]:
    
    result = score_user(raw_payload, weights_path)

    # Track KEY → ID mapping (SAFE)
    track_key_to_id = {
        "DA": "dip_data_analytics",
        "DE": "dip_data_engineering",
        "DS": "dip_data_science"
    }

    # Sort tracks
    sorted_tracks = sorted(result.final_track_scores.items(), key=lambda x: x[1], reverse=True)
    top_1_track, top_1_score = sorted_tracks[0]
    top_2_track, top_2_score = sorted_tracks[1]

    # Confidence score
    confidence_score = round(max(0.0, top_1_score - top_2_score), 4)

    # Correct fallback logic (based on BASE score, not final)
    highest_base = max(result.base_scores.values())

    if highest_base < 0.40:
        return {
            "immediate_enrollment_id": result.immediate_destination,
            "projected_specialization_id": "dip_undecided",
            "confidence_score": 0.00,
            "ui_message": "Let's build a strong foundation first. We'll guide you to the right specialization step by step."
        }

    # Dual-track logic
    if confidence_score < 0.05:
        t1_label = TRACK_LABELS[top_1_track]
        t2_label = TRACK_LABELS[top_2_track]

        return {
            "immediate_enrollment_id": result.immediate_destination,
            "projected_specialization_id": "dip_dual_track",
            "confidence_score": confidence_score,
            "ui_message": f"You show strong potential in both {t1_label} and {t2_label}. We'll help you decide after your foundation phase."
        }

    # Normal routing
    projected_id = track_key_to_id[top_1_track]

    return {
        "immediate_enrollment_id": result.immediate_destination,
        "projected_specialization_id": projected_id,
        "confidence_score": confidence_score,
        "ui_message": result.message
    }