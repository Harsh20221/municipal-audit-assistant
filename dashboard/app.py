"""Guided upload dashboard. Page names are fixed. Lists come from the API."""

from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

API = os.getenv("DASHBOARD_API_URL", "http://127.0.0.1:8000").rstrip("/")
PAGES = (
    "Check a case",
    "Findings",
    "Project portfolio",
    "Evaluation",
    "Guide",
)


def main() -> None:
    st.set_page_config(page_title="Municipal Audit Assistant", layout="wide")
    st.sidebar.title("Municipal Audit Assistant")
    page = st.sidebar.radio("Pages", PAGES)
    if page == "Check a case":
        check_case()
    elif page == "Findings":
        findings_page()
    elif page == "Project portfolio":
        portfolio_page()
    elif page == "Evaluation":
        evaluation_page()
    else:
        guide_page()


def check_case() -> None:
    st.header("Check a case")
    step = st.session_state.setdefault("step", 1)
    st.caption(f"Step {step} of 4")
    families = _get("/api/v1/families").get("families", [])
    if not families:
        st.warning("The API returned no document families.")
        return
    if step == 1:
        _step_family(families)
    elif step == 2:
        _step_requirements()
    elif step == 3:
        _step_upload()
    else:
        _step_results()


def _step_family(families: list[dict]) -> None:
    st.subheader("Choose what to check")
    columns = st.columns(min(len(families), 3) or 1)
    for index, family in enumerate(families):
        with columns[index % len(columns)]:
            st.markdown(f"**{family['name']}**")
            st.write(family["description"])
            if st.button("Use this", key=f"pick_{family['name']}"):
                st.session_state["family"] = family["name"]
                st.session_state["requirements"] = _get(
                    f"/api/v1/families/{family['name']}/requirements"
                )
                st.session_state["step"] = 2
                st.session_state.pop("validation", None)
                st.session_state.pop("audit", None)
                st.rerun()


def _step_requirements() -> None:
    requirements = st.session_state.get("requirements") or {}
    st.subheader(requirements.get("description") or "Documents this check needs")
    for notice in requirements.get("notices") or []:
        st.info(notice)
    for document in requirements.get("documents") or []:
        badge = "Required" if document["required"] else "Optional"
        repeats = "Multiple files allowed" if document["allow_multiple"] else "One file"
        st.markdown(f"### {document['label']}  \n`{badge}` · `{repeats}`")
        st.write(document["description"])
        st.write("Must contain: " + ", ".join(document["key_fields_it_must_contain"]))
        st.write("Enables: " + ", ".join(document["needed_for"]))
        st.write("Accepted format: " + ", ".join(document["accepted_formats"]))
        st.write(document["what_to_look_for"])
        st.link_button(
            "Download a sample",
            API + document["sample_url"],
        )
    _nav(back=1, forward=3, forward_label="Continue to upload")


def _step_upload() -> None:
    requirements = st.session_state.get("requirements") or {}
    documents = requirements.get("documents") or []
    st.subheader("Upload one file for each document")
    chosen: list[tuple[str, object]] = []
    required = [item for item in documents if item["required"]]
    present = 0
    for document in documents:
        badge = "Required" if document["required"] else "Optional"
        label = f"{document['label']} ({badge})"
        uploads = st.file_uploader(
            label,
            type=["pdf"],
            accept_multiple_files=bool(document["allow_multiple"]),
            key=f"file_{document['name']}",
        )
        files = uploads if isinstance(uploads, list) else ([uploads] if uploads else [])
        if document["required"] and files:
            present += 1
        for item in files:
            chosen.append((document["name"], item))
    st.progress(0 if not required else present / len(required))
    st.write(f"{present} of {len(required)} required documents")
    allow_partial = st.checkbox(
        "Run with available documents",
        help=(
            "Audit even when a required document is missing. "
            "Missing checks are reported, not passed."
        ),
    )
    if st.button("Validate documents"):
        st.session_state["validation"] = _post_files(
            f"/api/v1/cases/{st.session_state['family']}/validate",
            chosen,
        )
    validation = st.session_state.get("validation")
    if validation and "error" not in validation:
        for row in validation.get("files") or []:
            _status_line(row["status"], f"{row['filename']}: {row['message']}")
        st.write(f"Bundle: {validation.get('verdict')}")
    ready = present == len(required) or allow_partial
    if st.button("Run audit", disabled=not ready or not chosen):
        result = _post_files(
            f"/api/v1/cases/{st.session_state['family']}/audit",
            chosen,
            extra={"run_with_available": str(allow_partial).lower()},
        )
        if "error" in result:
            st.error(result["error"]["message"])
        else:
            st.session_state["audit"] = result
            st.session_state["step"] = 4
            st.rerun()
    _nav(back=2, forward=None)


def _step_results() -> None:
    audit = st.session_state.get("audit") or {}
    if not audit:
        st.info("Run an audit from the upload step.")
        _nav(back=3, forward=None)
        return
    risk = audit.get("risk") or {}
    st.subheader(f"Case {audit.get('case_id')}")
    if risk:
        st.metric("Risk score", f"{risk['score']} ({risk['band']})")
    else:
        st.write("No risk score was stored. This requires manual verification.")
    st.info(audit.get("layer4_note", ""))
    st.markdown("### Findings")
    for finding in audit.get("findings") or []:
        _finding_card(finding)
    coverage = audit.get("coverage") or {}
    left, right = st.columns(2)
    with left:
        st.markdown("### Checks that ran")
        for rule_id in coverage.get("rules_run") or []:
            st.write(rule_id)
        if not coverage.get("rules_run"):
            st.write("None")
    with right:
        st.markdown("### Checks that could not run (missing documents)")
        skipped = coverage.get("rules_skipped") or []
        if skipped:
            st.dataframe(
                [{"rule": item["rule_id"], "reason": item["reason"]} for item in skipped],
                hide_index=True,
            )
        else:
            st.write("None")
    _nav(back=3, forward=None)


def _finding_card(finding: dict) -> None:
    st.markdown(
        f"**{finding['rule_id']}** · {finding['severity']} · layer {finding['layer']} · "
        f"status {finding['review_status']}"
    )
    st.write(f"Expected: {finding.get('expected_value')}")
    st.write(f"Actual: {finding.get('actual_value')}")
    for evidence in finding.get("evidence") or []:
        name = evidence.get("filename") or evidence.get("doc_id")
        st.caption(f"Evidence: {name}, page {evidence.get('page')}, field {evidence.get('field')}")
    if finding.get("explanation"):
        st.write(finding["explanation"])
    else:
        st.caption("This result requires manual verification.")
    confirmed, rejected = st.columns(2)
    with confirmed:
        if st.button("Confirmed", key=f"yes_{finding['finding_id']}"):
            _review(finding["finding_id"], "confirmed")
    with rejected:
        if st.button("False positive", key=f"no_{finding['finding_id']}"):
            _review(finding["finding_id"], "false_positive")


def findings_page() -> None:
    st.header("Findings")
    families = [item["name"] for item in _get("/api/v1/families").get("families", [])]
    family = st.selectbox("Family", ["All", *families])
    severity = st.selectbox("Severity", ["All", "low", "medium", "high"])
    rule_id = st.text_input("Rule")
    status = st.selectbox("Status", ["All", "open", "confirmed", "false_positive"])
    params = {}
    if family != "All":
        params["family"] = family
    if severity != "All":
        params["severity"] = severity
    if rule_id.strip():
        params["rule_id"] = rule_id.strip()
    if status != "All":
        params["status"] = status
    payload = _get("/api/v1/findings", params=params)
    rows = payload.get("findings") or []
    if not rows:
        st.write("No findings match these filters.")
        return
    st.dataframe(
        [
            {
                "family": row["family"],
                "rule": row["rule_id"],
                "severity": row["severity"],
                "status": row["review_status"],
                "expected": row["expected_value"],
                "actual": row["actual_value"],
            }
            for row in rows
        ],
        hide_index=True,
    )
    st.caption("Every finding requires manual verification.")


def portfolio_page() -> None:
    st.header("Project portfolio")
    families = _get("/api/v1/families").get("families", [])
    shown = False
    for family in families:
        if not family.get("has_portfolio"):
            continue
        shown = True
        payload = _get(f"/api/v1/families/{family['name']}/portfolio")
        if "error" in payload:
            st.error(payload["error"]["message"])
            continue
        st.subheader(family["name"])
        st.caption(payload.get("note") or "These points require manual verification.")
        frame = pd.DataFrame(payload.get("points") or [])
        if frame.empty:
            st.write("No progress reports are stored yet.")
            continue
        st.scatter_chart(
            frame,
            x="physical_pct",
            y="financial_pct",
        )
    if not shown:
        st.write("No enabled family provides a progress comparison.")


def evaluation_page() -> None:
    st.header("Evaluation")
    summary = _get("/api/v1/evaluation/summary")
    st.info(summary.get("note") or "")
    sections = (
        ("Tier B rules", "tier_b_rules"),
        ("Tier B ablation", "tier_b_ablation"),
        ("Tier B extraction", "tier_b_extraction"),
        ("Tier A extraction", "tier_a_extraction"),
        ("Explanation guardrail", "explanation_guardrail"),
    )
    for title, key in sections:
        st.subheader(title)
        text = summary.get(key) or "_No report saved yet._"
        st.markdown(text)


def guide_page() -> None:
    st.header("Guide")
    guide = _get("/api/v1/guide")
    st.subheader("Limitations")
    for line in guide.get("limitations") or []:
        st.write(line)
    st.subheader("What each check needs")
    for family in guide.get("families") or []:
        st.markdown(f"### {family['family']}")
        st.write(family.get("description") or "")
        for document in family.get("documents") or []:
            checks = ", ".join(document.get("needed_for") or [])
            st.write(f"- {document['label']}: {document['description']} Enables {checks}.")
    st.subheader("Public example documents")
    st.markdown(guide.get("sources_markdown") or "")


def _nav(back: int | None, forward: int | None, forward_label: str = "Continue") -> None:
    left, right = st.columns(2)
    if back is not None and left.button("Back"):
        st.session_state["step"] = back
        st.rerun()
    if forward is not None and right.button(forward_label):
        st.session_state["step"] = forward
        st.rerun()


def _status_line(status: str, message: str) -> None:
    if status == "ok":
        st.success(message)
    elif status == "warning":
        st.warning(message)
    else:
        st.error(message)


def _review(finding_id: str, status: str) -> None:
    updated = _send("PATCH", f"/api/v1/findings/{finding_id}", json={"review_status": status})
    audit = st.session_state.get("audit") or {}
    for finding in audit.get("findings") or []:
        if finding["finding_id"] == finding_id and "error" not in updated:
            finding["review_status"] = updated["review_status"]
    st.rerun()


def _post_files(path: str, chosen: list[tuple[str, object]], extra: dict | None = None) -> dict:
    files = []
    for slot, upload in chosen:
        files.append(("files", (upload.name, upload.getvalue(), "application/pdf")))
        files.append(("slots", (None, slot)))
    for key, value in (extra or {}).items():
        files.append((key, (None, value)))
    try:
        response = httpx.post(API + path, files=files, timeout=120)
    except httpx.HTTPError as exc:
        return {"error": {"code": "connection", "message": str(exc)}}
    return _decode(response)


def _get(path: str, params: dict | None = None) -> dict:
    return _send("GET", path, params=params)


def _send(method: str, path: str, **kwargs) -> dict:
    try:
        response = httpx.request(method, API + path, timeout=60, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"The API is not reachable at {API}. Start it, then refresh. ({exc})")
        return {}
    return _decode(response)


def _decode(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {"error": {"code": str(response.status_code), "message": response.text}}
    if response.status_code >= 400 and "error" not in payload:
        return {"error": {"code": str(response.status_code), "message": response.text}}
    return payload


if __name__ == "__main__":
    main()
else:
    main()
