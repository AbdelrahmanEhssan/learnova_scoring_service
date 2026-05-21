# LearnNova Admin Dashboard - Visualization Spec Reviewed

Prepared for: Flutter Frontend Team  
Prepared by: Data & Intelligence Team  
Sprint: Sprint 6  
Task: 6.4 - Dashboard Visualization Spec

## 1. Purpose

This document defines the exact data structures required by the Admin Dashboard charts so the frontend team can build the UI without guessing field names, chart axes, or drill-down behavior.

The reviewed implementation keeps the Supabase RPC approach as the frontend-safe delivery method. The frontend should call RPC functions instead of running raw SQL directly. However, this spec also includes the exact SQL logic behind the drill-down because Task 6.4 explicitly requires it.

## 2. Chart 1 - Risk Radar Scatter Plot

RPC name: `get_risk_radar_data`

Frontend call:

```dart
final radarData = await supabase.rpc('get_risk_radar_data');
```

Chart type: Scatter plot

Required JSON shape:

```json
[
  { "user_id": "u123", "sentiment": -0.6, "score": 0.45 },
  { "user_id": "u456", "sentiment": 0.2, "score": 0.82 },
  { "user_id": "u789", "sentiment": -0.4, "score": 0.58 }
]
```

Field meaning:

| Field | Type | Meaning |
|---|---|---|
| `user_id` | string | Student identifier |
| `sentiment` | number | Latest or aggregated sentiment score, usually from -1 to +1 |
| `score` | number | Latest or aggregated quiz score, normalized from 0 to 1 |

Recommended axes:

| Axis | Field |
|---|---|
| X-axis | `sentiment` |
| Y-axis | `score` |

Risk interpretation:

| Pattern | Meaning |
|---|---|
| Low sentiment + low score | Highest-risk student |
| High sentiment + high score | Healthy student |
| Low sentiment + high score | Emotionally struggling but academically performing |
| High sentiment + low score | Motivated but academically weak |

## 3. Chart 2 - Struggle Map Bar Chart

RPC name: `get_struggle_map_data`

Frontend call:

```dart
final struggleData = await supabase.rpc('get_struggle_map_data');
```

Chart type: Bar chart

Required JSON shape:

```json
[
  { "topic_id": "sf_python_loops", "name": "Python Loops", "struggle_index": 0.85 },
  { "topic_id": "sf_sql_joins", "name": "SQL Joins", "struggle_index": 0.78 },
  { "topic_id": "sf_statistics_variance", "name": "Variance", "struggle_index": 0.64 }
]
```

Field meaning:

| Field | Type | Meaning |
|---|---|---|
| `topic_id` | string | Topic identifier |
| `name` | string | Human-readable topic name shown in the bar label |
| `struggle_index` | number | Normalized topic struggle value from 0 to 1 |

Recommended chart behavior:

- Sort bars from highest `struggle_index` to lowest.
- Limit the default chart to the top 10 topics.
- When the admin clicks a bar, call `get_topic_drilldown` with that `topic_id`.

## 4. Chart 3 - Momentum Line Chart

RPC name: `get_momentum_data`

Frontend call:

```dart
final momentumData = await supabase.rpc('get_momentum_data');
```

Chart type: Line chart

Required JSON shape:

```json
[
  { "date": "2026-02-14", "velocity": 0.12 },
  { "date": "2026-02-15", "velocity": 0.18 },
  { "date": "2026-02-16", "velocity": 0.15 }
]
```

Field meaning:

| Field | Type | Meaning |
|---|---|---|
| `date` | string | Date formatted as `YYYY-MM-DD` |
| `velocity` | number | Daily engagement velocity value |

Recommended axes:

| Axis | Field |
|---|---|
| X-axis | `date` |
| Y-axis | `velocity` |

Recommended chart behavior:

- Plot the most recent 30 days.
- Show rising velocity as positive momentum.
- Show falling velocity as a possible disengagement signal.

## 5. Drill-Down Query Spec

Purpose: When an admin clicks a topic in the Struggle Map, the dashboard should show the specific students currently failing that topic.

Required base SQL from Task 6.4:

```sql
SELECT user_id, latest_score, sentiment
FROM user_topic_performance
WHERE topic_id = 'X'
  AND latest_score < 0.6;
```

Reviewed parameterized SQL:

```sql
SELECT
    user_id,
    latest_score,
    sentiment
FROM user_topic_performance
WHERE topic_id = :topic_id
  AND latest_score < 0.60
ORDER BY latest_score ASC, sentiment ASC NULLS LAST, user_id ASC;
```

Frontend-safe RPC name: `get_topic_drilldown`

Frontend call:

```dart
final drillDown = await supabase.rpc(
  'get_topic_drilldown',
  params: {'p_topic_id': 'sf_python_loops'},
);
```

Expected JSON shape:

```json
[
  { "user_id": "u9942", "latest_score": 0.45, "sentiment": -0.85 },
  { "user_id": "u1058", "latest_score": 0.52, "sentiment": -0.40 }
]
```

Field meaning:

| Field | Type | Meaning |
|---|---|---|
| `user_id` | string | Student identifier |
| `latest_score` | number | Student's latest score in the clicked topic |
| `sentiment` | number | Student's latest sentiment for that topic |

## 6. Optional Enhancement - Predictive Funnel

This chart is not required by the original Task 6.4 chart list, but it was kept because Sprint 6.2 already created the foundation conversion view.

RPC name: `get_predictive_funnel_data`

Frontend call:

```dart
final funnelData = await supabase.rpc('get_predictive_funnel_data');
```

Expected JSON shape:

```json
[
  {
    "projected_specialization_id": "dip_data_analysis",
    "projected_diploma_name": "Data Analysis",
    "foundation_starters": 120,
    "checkpoint_passers": 96,
    "entered_projected_diploma": 84,
    "checkpoint_pass_rate_pct": 80.0,
    "foundation_to_projected_conversion_rate_pct": 70.0
  }
]
```

Final positioning:

- The three required charts remain the official Task 6.4 deliverable.
- The predictive funnel is kept as an optional dashboard enhancement.

## 7. Final Frontend Contract Summary

| UI Component | RPC | Required Fields |
|---|---|---|
| Risk Radar scatter | `get_risk_radar_data` | `user_id`, `sentiment`, `score` |
| Struggle Map bar | `get_struggle_map_data` | `topic_id`, `name`, `struggle_index` |
| Momentum line | `get_momentum_data` | `date`, `velocity` |
| Topic drill-down table | `get_topic_drilldown` | `user_id`, `latest_score`, `sentiment` |
| Predictive funnel optional | `get_predictive_funnel_data` | foundation conversion fields |

## 8. Notes for Flutter Implementation

The frontend should not execute raw SQL directly. The SQL is documented for clarity and review, but Flutter should call the RPC functions through Supabase.

The data returned from each RPC is already chart-ready JSON. The frontend should only map the returned fields into the charting library.
