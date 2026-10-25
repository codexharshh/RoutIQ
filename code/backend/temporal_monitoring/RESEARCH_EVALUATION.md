# RoutIQ Temporal Review Evaluation

The evaluation command compares the current quality-aware temporal review rule with a documented class-and-distance baseline. It does not train a model or establish that damage was repaired. `uncertain` is abstention, not a negative or repaired label. Metrics describe only the supplied labelled pairs; they are not calibrated probabilities.

Run from `backend` after preparing a UTF-8 CSV:

```powershell
.\.venv\Scripts\python.exe -m temporal_monitoring.evaluation path\to\labelled_pairs.csv --validate-only
.\.venv\Scripts\python.exe -m temporal_monitoring.evaluation path\to\labelled_pairs.csv --distance-threshold-m 15
```

The validation-only command checks columns and row values, reports the row count and input SHA-256, and does not calculate performance metrics.

## CSV schema

The header must contain these columns exactly once. Extra columns are permitted, but every row must have the same number of fields as the header.

| Column(s) | Requirements |
| --- | --- |
| `label` | `same_damage` or `different_damage`, assigned by human review |
| `damage_class_a`, `damage_class_b` | Non-empty recorded class names |
| `latitude_a`, `longitude_a`, `latitude_b`, `longitude_b` | Finite WGS-84 decimals in range. A coordinate pair may be blank together to represent unavailable GPS; a half-present pair is invalid. |
| `observed_at_a`, `observed_at_b` | ISO 8601 timestamps with an explicit timezone offset |
| `confidence_a`, `confidence_b` | Finite values from 0 to 1 |
| `gps_accuracy_m_a`, `gps_accuracy_m_b` | Blank or finite non-negative meters |
| `image_width_a`, `image_height_a`, `image_width_b`, `image_height_b` | Blank or positive integer pixel dimensions; width and height must be both present or both blank for each observation |

Example header and one illustrative row (not research data):

```csv
label,damage_class_a,damage_class_b,latitude_a,longitude_a,latitude_b,longitude_b,observed_at_a,observed_at_b,confidence_a,confidence_b,gps_accuracy_m_a,gps_accuracy_m_b,image_width_a,image_height_a,image_width_b,image_height_b
same_damage,pothole,pothole,28.6139,77.2090,28.6140,77.2091,2026-01-01T08:00:00+00:00,2026-01-02T08:00:00+00:00,0.91,0.88,4.5,6,1280,720,1280,720
```

## Annotation and split protocol

### Practical collection checklist

- [ ] Confirm permissions, image provenance, and the approved retention location before collecting road imagery.
- [ ] Assign each route segment, direction, and pass an identifier in a protected manifest; keep identifiers out of public reports.
- [ ] Record capture timestamps with time zones, GPS source and reported accuracy, image dimensions, visibility conditions, and missing-data reasons.
- [ ] Collect repeat passes under the predeclared interval and route protocol. Retain source image references so reviewers can inspect the actual evidence.
- [ ] Obtain independent pair labels from two reviewers, preserve both decisions, and adjudicate disagreements using the documented process.
- [ ] Freeze route-separated development and evaluation splits, label definitions, threshold, software revision, and input hashes before evaluating.
- [ ] Validate the completed file before computing metrics:

```powershell
Set-Location D:\RoutIQ\code\backend
.\.venv\Scripts\python.exe -m temporal_monitoring.evaluation path\to\labelled_pairs.csv --validate-only
```

This command validates only. It does not calculate performance metrics. Do not use synthetic tests or unlabeled observations as empirical results.

1. Define a repeat-pass sampling unit before collection, including route segment, direction, time window, and the minimum separation needed to count as a new pass. Retain source observation IDs and image references in a protected annotation manifest rather than adding them to the evaluation CSV.
2. Have two reviewers independently inspect each pair and assign `same_damage` only when the same physical damage is supported by the image evidence. Assign `different_damage` when both observations are usable and show distinct damage. Exclude pairs with insufficient visual evidence from the binary CSV and record them separately as unlabelled exclusions; do not convert missing detections into repaired labels.
3. Preserve both initial reviewer decisions. Resolve disagreement through a third reviewer or a documented consensus meeting, and record the adjudicated label and disagreement count in a separate audit file. Report inter-reviewer agreement and the adjudication procedure alongside any results.
4. Record coordinate source, reported GPS accuracy, observation timestamps, image dimensions, route and pass identifiers, weather or visibility notes where available, and dataset provenance. Never treat device-current location as photo GPS. Keep the original evidence access-controlled and apply the project's retention policy.
5. Split by route or route segment before selecting pairs so observations from the same physical area do not leak across development and test sets. Fix and publish the split manifest, label definitions, threshold, software revision, and input file hashes before comparing methods.
6. Report class balance and each metric with its denominator. A metric with no applicable denominator is `null` (not zero). Report abstention rate and coverage beside error among non-abstained decisions. Stratify by recorded quality while explaining the heuristic strata. Do not interpret the heuristic score as a calibrated probability.

The report includes candidate-match precision and recall, false-match rate among labelled negative pairs, abstention rate, coverage, error rate among non-abstained decisions, quality-stratified results, and the SHA-256 digest of the input file. The baseline predicts a candidate match when classes agree and the distance is within the selected threshold; it does not use time or quality. Synthetic unit-test fixtures validate software behavior only and must never be presented as research performance.

The blank header-only template is [`annotation_template.csv`](annotation_template.csv). Replace it with independently reviewed records; the blank template is not an evaluation dataset.
