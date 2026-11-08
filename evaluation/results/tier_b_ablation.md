# Tier B layer ablation

Synthetic structured data only. Families are scored separately and are
not averaged into one number. Real documents have no anomaly ground truth.

Tuning seed: 42. Held-out seed: 43.
The held-out corpus is a new draw from the same quota generator.
Thresholds were chosen on the tuning seed only.

Chosen parameters:
- z_threshold: 5
- iqr_k: 1.5
- contamination: 0.05
- min_peer_group: 8
- Isolation Forest random_state: 42

Recall on injected errors is the share of single-error and multi-error
cases flagged. Recall on needs_layer4 is the share of those statistical
cases flagged. The false-positive rate uses clean and hard-negative
cases only. A needs_layer4 miss is not counted as a false negative here.
Layer 4 false positives are shown as counts, not removed.

Selection rule on seed 42: among z_threshold in {3, 4, 5}, iqr_k in
{1.5, 2.5, 3}, and contamination in {0.02, 0.03, 0.05}, keep settings
whose z-score+IQR and Isolation Forest false-positive rates are each
at or below 0.10 in both families, then take the highest average
needs_layer4 recall. Ties prefer the lower average false-positive rate.

# Seed 42 (tuning result)

## project

| method | injected recall | needs_layer4 recall | false positives | false-positive rate |
| --- | ---: | ---: | ---: | ---: |
| rules only | 81/81 = 1.000 | 0/9 = 0.000 | 0/60 | 0.000 |
| z-score+IQR only | 3/81 = 0.037 | 2/9 = 0.222 | 0/60 | 0.000 |
| Isolation Forest only | 7/81 = 0.086 | 1/9 = 0.111 | 0/60 | 0.000 |
| combined | 81/81 = 1.000 | 2/9 = 0.222 | 0/60 | 0.000 |

## property_tax

| method | injected recall | needs_layer4 recall | false positives | false-positive rate |
| --- | ---: | ---: | ---: | ---: |
| rules only | 84/84 = 1.000 | 0/9 = 0.000 | 0/207 | 0.000 |
| z-score+IQR only | 7/84 = 0.083 | 8/9 = 0.889 | 0/207 | 0.000 |
| Isolation Forest only | 10/84 = 0.119 | 7/9 = 0.778 | 0/207 | 0.000 |
| combined | 84/84 = 1.000 | 8/9 = 0.889 | 0/207 | 0.000 |

# Seed 43 (held-out result)

## project

| method | injected recall | needs_layer4 recall | false positives | false-positive rate |
| --- | ---: | ---: | ---: | ---: |
| rules only | 81/81 = 1.000 | 0/9 = 0.000 | 0/60 | 0.000 |
| z-score+IQR only | 4/81 = 0.049 | 2/9 = 0.222 | 0/60 | 0.000 |
| Isolation Forest only | 6/81 = 0.074 | 2/9 = 0.222 | 1/60 | 0.017 |
| combined | 81/81 = 1.000 | 2/9 = 0.222 | 1/60 | 0.017 |

## property_tax

| method | injected recall | needs_layer4 recall | false positives | false-positive rate |
| --- | ---: | ---: | ---: | ---: |
| rules only | 84/84 = 1.000 | 0/9 = 0.000 | 0/207 | 0.000 |
| z-score+IQR only | 6/84 = 0.071 | 8/9 = 0.889 | 0/207 | 0.000 |
| Isolation Forest only | 11/84 = 0.131 | 6/9 = 0.667 | 0/207 | 0.000 |
| combined | 84/84 = 1.000 | 8/9 = 0.889 | 0/207 | 0.000 |
