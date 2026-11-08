"""Peer-group z-score, IQR, and Isolation Forest on a family feature frame.

Z-score and IQR compare a case with other rows in the same peer_group.
Isolation Forest is also fit inside each peer group, after StandardScaler.
A flag is not emitted for a feature when a layer 1-3 finding already cites
that field on the same case.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from engine.finding import Evidence, Finding

CASE_KEY = "case_key"
PEER = "peer_group"
METHOD_RULES = {
    "zscore": "L4-ZSCORE",
    "iqr": "L4-IQR",
    "iforest": "L4-IFOREST",
}
_NOTE_SUFFIX = " Requires manual verification."


@dataclass(frozen=True)
class StatFlag:
    case_key: str
    method: str
    details: tuple[tuple[str, str], ...]
    strength: float

    @property
    def features(self) -> tuple[str, ...]:
        return tuple(name for name, _phrase in self.details)

    @property
    def note(self) -> str:
        body = "; ".join(phrase for _name, phrase in self.details)
        return f"{body}.{_NOTE_SUFFIX}"


def numeric_columns(frame: pd.DataFrame) -> list[str]:
    columns = []
    for name in frame.columns:
        if name in {CASE_KEY, PEER}:
            continue
        if pd.api.types.is_numeric_dtype(frame[name]):
            columns.append(str(name))
    return columns


def population_zscores(values: np.ndarray) -> np.ndarray:
    """Z-scores with the population standard deviation (ddof=0). NaNs stay NaN."""
    finite = np.isfinite(values)
    out = np.full(values.shape, np.nan, dtype=float)
    if int(finite.sum()) == 0:
        return out
    mean = float(np.mean(values[finite]))
    std = float(np.std(values[finite], ddof=0))
    if std == 0:
        return out
    out[finite] = (values[finite] - mean) / std
    return out


def iqr_fences(values: np.ndarray, k: float) -> tuple[float, float] | None:
    """Tukey fences from the linear 25th and 75th percentiles. None when IQR is 0."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    q1 = float(np.percentile(finite, 25))
    q3 = float(np.percentile(finite, 75))
    span = q3 - q1
    if span == 0:
        return None
    return q1 - k * span, q3 + k * span


def scale_columns(matrix: np.ndarray) -> np.ndarray:
    """StandardScaler (mean 0, population std 1). Zero-variance columns become 0."""
    if matrix.size == 0:
        return matrix
    scaled = StandardScaler().fit_transform(matrix)
    return np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)


def zscore_flags(frame: pd.DataFrame, *, threshold: float, min_peer_group: int) -> list[StatFlag]:
    return _univariate_flags(
        frame,
        method="zscore",
        min_peer_group=min_peer_group,
        explain=_zscore_details,
        threshold=threshold,
    )


def iqr_flags(frame: pd.DataFrame, *, k: float, min_peer_group: int) -> list[StatFlag]:
    return _univariate_flags(
        frame,
        method="iqr",
        min_peer_group=min_peer_group,
        explain=_iqr_details,
        k=k,
    )


def isolation_forest_flags(
    frame: pd.DataFrame,
    *,
    contamination: float,
    min_peer_group: int,
    random_state: int,
) -> list[StatFlag]:
    flags: list[StatFlag] = []
    columns = numeric_columns(frame)
    if not columns or not 0 < contamination < 0.5:
        return flags
    for _peer, group in _peer_groups(frame):
        if len(group) < min_peer_group:
            continue
        usable = [name for name in columns if group[name].notna().any()]
        if not usable:
            continue
        filled = group[usable].apply(lambda series: series.fillna(series.median()), axis=0)
        matrix = filled.to_numpy(dtype=float)
        keep = [index for index, name in enumerate(usable) if np.nanstd(matrix[:, index]) > 0]
        if not keep:
            continue
        scaled = scale_columns(matrix[:, keep])
        model = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=100,
            n_jobs=1,
        )
        predicted = model.fit_predict(scaled)
        kept_names = [usable[index] for index in keep]
        for row_index, label in enumerate(predicted):
            if label != -1:
                continue
            strength = float(np.max(np.abs(scaled[row_index])))
            order = np.argsort(-np.abs(scaled[row_index]))
            details = []
            for feature_index in order[:3]:
                feature = kept_names[int(feature_index)]
                value = scaled[row_index, int(feature_index)]
                details.append((feature, f"{feature} scaled={value:.2f}"))
            flags.append(
                StatFlag(
                    case_key=str(group.iloc[row_index][CASE_KEY]),
                    method="iforest",
                    details=tuple(details),
                    strength=strength,
                )
            )
    return flags


def suppress_rule_overlaps(
    flags: list[StatFlag],
    occupied: set[tuple[str, str]],
    field_map: dict[str, str],
) -> list[StatFlag]:
    """Drop features already cited by a rule finding on the same case."""
    kept: list[StatFlag] = []
    for flag in flags:
        details = []
        for feature, phrase in flag.details:
            field = field_map.get(feature, feature)
            if (flag.case_key, field) in occupied or (flag.case_key, feature) in occupied:
                continue
            details.append((feature, phrase))
        if not details:
            continue
        kept.append(
            StatFlag(
                case_key=flag.case_key,
                method=flag.method,
                details=tuple(details),
                strength=flag.strength,
            )
        )
    return kept


def occupied_from_findings(family, session, findings: list[Finding]) -> set[tuple[str, str]]:
    occupied: set[tuple[str, str]] = set()
    for finding in findings:
        if finding.layer >= 4:
            continue
        case_key = family.case_key_for_finding(session, finding.entity_type, finding.entity_id)
        if case_key is None:
            continue
        for piece in finding.evidence:
            occupied.add((str(case_key), piece.field))
    return occupied


def findings_from_flags(
    flags: list[StatFlag],
    *,
    family: str,
    entity_type: str,
    rule_version: str,
    z_threshold: float,
    iqr_k: float,
    contamination: float,
) -> list[Finding]:
    expected = {
        "zscore": f"abs(z) <= {z_threshold:g} inside the peer group",
        "iqr": f"inside Tukey fences with k={iqr_k:g} inside the peer group",
        "iforest": f"Isolation Forest inlier at contamination {contamination:g}",
    }
    stored: list[Finding] = []
    for flag in flags:
        note = flag.note
        if len(note) > 480:
            note = note[:477] + "..."
        stored.append(
            Finding(
                family=family,
                rule_id=METHOD_RULES[flag.method],
                layer=4,
                entity_type=entity_type,
                entity_id=flag.case_key,
                severity="medium",
                expected_value=expected[flag.method],
                actual_value=note,
                difference=f"{flag.strength:.4f}",
                evidence=[Evidence(None, 1, feature) for feature in flag.features],
                rule_version=rule_version,
            )
        )
    return stored


def layer4_findings(family, session, settings, rule_findings: list[Finding]) -> list[Finding]:
    frame = family.feature_frame(session)
    flags = (
        zscore_flags(frame, threshold=settings.z_threshold, min_peer_group=settings.min_peer_group)
        + iqr_flags(frame, k=settings.iqr_k, min_peer_group=settings.min_peer_group)
        + isolation_forest_flags(
            frame,
            contamination=settings.contamination,
            min_peer_group=settings.min_peer_group,
            random_state=settings.random_state,
        )
    )
    flags = suppress_rule_overlaps(
        flags,
        occupied_from_findings(family, session, rule_findings),
        family.feature_fields(),
    )
    return findings_from_flags(
        flags,
        family=family.name,
        entity_type=family.case_entity_type,
        rule_version=family.version,
        z_threshold=settings.z_threshold,
        iqr_k=settings.iqr_k,
        contamination=settings.contamination,
    )


def _peer_groups(frame: pd.DataFrame):
    if PEER not in frame.columns:
        yield "all", frame
        return
    yield from frame.groupby(PEER, dropna=False, sort=False)


def _univariate_flags(frame, *, method, min_peer_group, explain, **kwargs) -> list[StatFlag]:
    flags: list[StatFlag] = []
    columns = numeric_columns(frame)
    for _peer, group in _peer_groups(frame):
        if len(group) < min_peer_group:
            continue
        per_case: dict[str, list[tuple[str, str, float]]] = {}
        for name in columns:
            values = group[name].to_numpy(dtype=float)
            if int(np.isfinite(values).sum()) < min_peer_group:
                continue
            explained = explain(values, **kwargs)
            if explained is None:
                continue
            phrases, strengths, mask = explained
            for position, flagged in enumerate(mask):
                if not flagged:
                    continue
                case_key = str(group.iloc[position][CASE_KEY])
                per_case.setdefault(case_key, []).append(
                    (name, f"{name} {phrases[position]}", float(strengths[position]))
                )
        for case_key, items in per_case.items():
            items.sort(key=lambda item: abs(item[2]), reverse=True)
            flags.append(
                StatFlag(
                    case_key=case_key,
                    method=method,
                    details=tuple((name, phrase) for name, phrase, _strength in items),
                    strength=max(abs(item[2]) for item in items),
                )
            )
    return flags


def _zscore_details(values: np.ndarray, *, threshold: float):
    scores = population_zscores(values)
    mask = np.isfinite(scores) & (np.abs(scores) > threshold)
    phrases = [f"z={score:.2f}" for score in scores]
    return phrases, scores, mask


def _iqr_details(values: np.ndarray, *, k: float):
    fences = iqr_fences(values, k)
    if fences is None:
        return None
    low, high = fences
    finite = np.isfinite(values)
    mask = finite & ((values < low) | (values > high))
    phrases = [f"value={value:.4g} outside [{low:.4g}, {high:.4g}]" for value in values]
    center = (low + high) / 2
    strengths = np.where(finite, np.abs(values - center), 0.0)
    return phrases, strengths, mask
