# Explanation guardrail

Sample of 12 stored layer 1-3 findings, seed 42.
A pass means every number in the explanation already appears in the finding, the text says 'requires manual verification', and it includes a manual-check line.
A failure is replaced by a template. Skipped-check text below is a template and does not call a model.

- guardrail_pass_rate=1.0000
- passed=12
- template_fallbacks=0

## Skipped-check examples

PR-001 was not run because a required document is missing (missing: progress_report). This requires manual verification.
What to check manually: add the missing document and run the check again.
PR-003 was not run because a required document is missing (missing: work_order, invoice). This requires manual verification.
What to check manually: add the missing document and run the check again.
