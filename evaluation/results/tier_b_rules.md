# Tier B rule metrics

Synthetic structured data only. This file does not use real documents,
and real documents have no anomaly ground truth. Property-tax rates
are illustrative. Each family is scored on its own answer key and the
families are not averaged together.

Each rule is scored independently, including cases with two or more
injected errors. needs_layer4 cases obey the rules and are reported as
expected misses, not as false negatives.

## project

| rule_id | tp | fp | fn | precision | recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| PR-001 | 9 | 0 | 0 | 1.000 | 1.000 |
| PR-002 | 8 | 0 | 0 | 1.000 | 1.000 |
| PR-003 | 9 | 0 | 0 | 1.000 | 1.000 |
| PR-004 | 9 | 0 | 0 | 1.000 | 1.000 |
| PR-005 | 8 | 0 | 0 | 1.000 | 1.000 |
| PR-006 | 11 | 0 | 0 | 1.000 | 1.000 |
| PR-007 | 9 | 0 | 0 | 1.000 | 1.000 |
| PR-008 | 8 | 0 | 0 | 1.000 | 1.000 |
| PR-009 | 8 | 0 | 0 | 1.000 | 1.000 |
| PR-010 | 8 | 0 | 0 | 1.000 | 1.000 |
| PR-011 | 9 | 0 | 0 | 1.000 | 1.000 |

Categories: clean 44, hard_negative 16, single_error 66, multi_error 15, needs_layer4 9.
Micro precision: 1.000. Micro recall: 1.000.
False-positive rate on clean and hard-negative cases: 0/60 = 0.000.
Expected misses by rules: 9/9 needs_layer4 cases had no rule finding.
Unexpected rule hits on needs_layer4: 0.

## property_tax

| rule_id | tp | fp | fn | precision | recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| PT-001 | 12 | 0 | 0 | 1.000 | 1.000 |
| PT-002 | 12 | 0 | 0 | 1.000 | 1.000 |
| PT-003 | 12 | 0 | 0 | 1.000 | 1.000 |
| PT-004 | 12 | 0 | 0 | 1.000 | 1.000 |
| PT-005 | 12 | 0 | 0 | 1.000 | 1.000 |
| PT-006 | 15 | 0 | 0 | 1.000 | 1.000 |
| PT-007 | 15 | 0 | 0 | 1.000 | 1.000 |
| PT-008 | 15 | 0 | 0 | 1.000 | 1.000 |
| PT-009 | 9 | 0 | 0 | 1.000 | 1.000 |

Categories: clean 187, hard_negative 20, single_error 54, multi_error 30, needs_layer4 9.
Micro precision: 1.000. Micro recall: 1.000.
False-positive rate on clean and hard-negative cases: 0/207 = 0.000.
Expected misses by rules: 9/9 needs_layer4 cases had no rule finding.
Unexpected rule hits on needs_layer4: 0.
