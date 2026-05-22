from dotenv import load_dotenv

from mitchy.gemini_client import generate_mitchy_json


load_dotenv()


prompt = """
Return JSON only:
{
  "response_text": "SQL joins combine rows from tables using related columns.",
  "learning_state": "confused",
  "suggested_action": "rescue_explanation",
  "recommended_format": "textual",
  "confidence": 0.8,
  "metadata": {
    "short_reason": "test"
  }
}
"""

raw_text, error, model_name = generate_mitchy_json(prompt)

print("MODEL:", model_name)
print("ERROR:", error)
print("RAW:")
print(raw_text)
