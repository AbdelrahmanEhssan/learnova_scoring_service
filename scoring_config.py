from __future__ import annotations

TRACKS = ("DA", "DE", "DS")

TRACK_LABELS = {
    "DA": "Data Analytics",
    "DE": "Data Engineering",
    "DS": "Data Science",
}

IMMEDIATE_DESTINATION = "dip_shared_foundation"
FALLBACK_TRACK = "Foundational Literacy Track"
FALLBACK_THRESHOLD = 0.40

# Additive Scoring Weights
BASE_WEIGHT = 0.30
MODIFIER_WEIGHT = 0.70

# O*NET direct anchors for Tier 1
ONET_TRACK_BASE_FEATURE = {
    "DA": "artistic",
    "DE": "realistic",
    "DS": "investigative",
}

# Raw-score normalization ranges
FEATURE_RANGES = {
    # IQ
    # Audit fix: logical_reasoning section contains 15 questions, not 20.
    "logical_reasoning": (0, 15),
    "abstract_reasoning": (0, 20),
    # Spatial reasoning is retained in the competency model even though the
    # current IQ exam payload may not provide it yet. The engine safely falls
    # back to 0 when the key is absent.
    "spatial_reasoning": (0, 20),

    # IPIP (1-5)
    "openness": (1, 5),
    "conscientiousness": (1, 5),
    "extraversion": (1, 5),
    "agreeable": (1, 5),
    "neuroticism": (1, 5),

    # Soft Skills (0-10)
    "communication": (0, 10),
    "teamwork": (0, 10),
    "conflict_resolution": (0, 10),
    "ethics": (0, 10),
    "leadership": (0, 10),
    "problem_solving": (0, 10),
    "emotional_intelligence": (0, 10),
    "time_management": (0, 10),
    "accountability": (0, 10),

    # VARK (0-16)
    "visual": (0, 16),
    "auditory": (0, 16),
    "read_write": (0, 16),
    "kinesthetic": (0, 16),

    # O*NET / RIASEC (1-5)
    "realistic": (1, 5),
    "investigative": (1, 5),
    "artistic": (1, 5),
    "social": (1, 5),
    "enterprising": (1, 5),
    "conventional": (1, 5),
}

FEATURE_DISPLAY_NAMES = {
    "logical_reasoning": "logical reasoning",
    "abstract_reasoning": "abstract reasoning",
    "spatial_reasoning": "spatial reasoning",
    "openness": "openness",
    "conscientiousness": "conscientiousness",
    "extraversion": "extraversion",
    "agreeable": "agreeableness",
    "neuroticism": "emotional sensitivity",
    "communication": "communication",
    "teamwork": "teamwork",
    "conflict_resolution": "conflict resolution",
    "ethics": "ethics",
    "leadership": "leadership",
    "problem_solving": "problem solving",
    "emotional_intelligence": "emotional intelligence",
    "time_management": "time management",
    "accountability": "accountability",
    "visual": "visual learning preference",
    "auditory": "auditory learning preference",
    "read_write": "read/write learning preference",
    "kinesthetic": "kinesthetic learning preference",
    "realistic": "realistic interest",
    "investigative": "investigative interest",
    "artistic": "artistic interest",
    "social": "social interest",
    "enterprising": "enterprising interest",
    "conventional": "conventional interest",
}