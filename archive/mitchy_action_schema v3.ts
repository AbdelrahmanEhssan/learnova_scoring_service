/**
 * @file mitchy_action_schema_v2.ts
 * @description The V2 Action routing schema supporting the 9-State Affective Model, 
 * integrating Layer 1 NLP and Layer 3 Risk Analytics for the LearnNova Flutter UI.
 */

export enum SuggestedAction {
  // Conversational / Socratic Core
  NONE = 'none',                         // Standard chat (State: Flow/Mastered)
  SHOW_HINT = 'show_hint',               // Subtle UI nudge (State: Confused)
  QUIZ_REVIEW = 'quiz_review',           // Targeted flashcards (State: Misconception)
  RESOURCE_SUGGEST = 'resource_suggest', // Deep-dive link (State: Curious Inquiry)
  SIMPLIFY_PROBLEM = 'simplify_problem', // Re-render problem chunked (State: Anxious/Overwhelmed)

  // UI / App State Modifiers
  SHIFT_FORMAT = 'shift_format',         // Swap to Audio/Video Slot (State: Disengaged)
  HOLD_STATE = 'hold_state',             // Pauses timers silently (State: External Distraction)
  TAKE_BREAK = 'take_break',             // Full screen pause UI (State: Frustrated)
  END_SESSION_RECOMMENDATION = 'end_session_recommendation', // Daily wrap-up UI (State: Burnout)

  // Critical Safety
  CONTACT_ADMIN = 'contact_admin'        // Silent alert to dashboard (State: CRISIS)
}

/**
 * MitchyMetadata
 * Captures the LLM's internal affective classification based on the 9-State Model.
 */
export interface MitchyMetadata {
  detected_state: string;               // Must match one of the 9 states (e.g., 'misconception', 'flow')
  cognitive_load_estimate: number;      // Float 0.0 to 1.0 based on message complexity
}

export interface MitchyResponse {
  text: string;
  action: SuggestedAction;
  metadata: MitchyMetadata;
}

/**
 * StateChangeEvent
 * Fired to the data warehouse for cohort tracking and thesis analytics.
 */
export interface StateChangeEvent {
  event: 'mitchy_state_change';
  previous_state: string;
  new_state: string;
  time_in_previous_state_seconds: number;
  action_taken: SuggestedAction;
}