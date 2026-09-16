# Qualification Campaign Comparison

Owner: Issue #35  
Applies to: DECXIN AR0234 / Nori qualification campaigns  
Status: tooling implemented; physical campaign evidence pending delivered hardware

## Purpose

A single characterization JSON answers a **run-level** question. A qualification campaign answers a broader **system-change** question:

```text
Did the same qualification stages behave better, worse, or differently
across a firmware / SDK / host / transport / code change?
```

The campaign tooling intentionally composes the existing measurement tools rather than introducing another source of truth.

```text
run_ar0234_qualification.py
        ↓
Q1 / Q2 / Q3 / Q4 / Q5
        ↓
characterization v2 JSON per stage
        ↓
campaign.json
        ↓
compare_qualification_campaigns.py
        ↓
per-stage comparisons + campaign provenance delta
```

## Campaign manifest

`tools/run_ar0234_qualification.py` writes:

```text
<CAMPAIGN_DIR>/campaign.json
```

Schema:

```text
bividi.nori.qualification_campaign.v1
```

The manifest records host/platform, Git revision, selected device/mode, requested stages, explicit nominal FPS used for fault cadence, exact commands, stage timing/return codes, and paths to run evidence.

Physical Q6/Q7 faults remain explicitly marked as non-automated. A software SDK reopen is never promoted to physical unplug/power-cycle evidence.

## Comparing two campaigns

Use:

```bash
python tools/compare_qualification_campaigns.py \
  <BASELINE>/campaign.json \
  <CANDIDATE>/campaign.json \
  --markdown-out campaign-comparison.md \
  --json-out campaign-comparison.json
```

The tool compares matching qualification stages with `compare_nori_characterization.py`, then aggregates the stage verdicts.

Default stage coverage is the union of stages present in the two manifests. A missing stage is a FAIL because the campaigns are structurally incomplete for like-for-like qualification. When the comparison is intentionally partial, select stages explicitly:

```bash
python tools/compare_qualification_campaigns.py \
  baseline/campaign.json candidate/campaign.json \
  --stages q1,q2,q3
```

`--allow-missing-stages` downgrades missing-stage evidence to WARN. Use it only when the experiment design explicitly permits incomplete coverage.

## Provenance handling

Campaign identity is preserved separately:

```text
campaign ID
creation time
```

The report also preserves comparison-relevant provenance changes in:

```text
Git revision
hostname / OS / release / machine
device index / mode index
nominal FPS used for fault cadence
fault cadence
```

These provenance differences are **informational context**. They do not by themselves change PASS/WARN/FAIL. Per-run device/SDK/ISP/FPGA provenance remains handled by the v2 characterization comparator.

This distinction is deliberate: a changed revision, host, or requested test condition may explain a result, but the change itself is not proof of regression. The stage evidence determines the regression verdict.

## Optional gates

Campaign comparison forwards the same explicit numeric gates to every comparable stage:

```text
--max-fps-drop-pct
--max-host-p99-increase-pct
--max-es-p99-increase-pct
--max-imu-p99-increase-pct
--max-recovery-p95-increase-pct
--max-rss-growth-delta-mib-per-hour
```

No gate is active unless the operator supplies it. Limits must come from a requirement, experiment design, or established baseline policy rather than from the tool.

Cross-mode comparisons remain FAIL by default. `--allow-mode-change` downgrades the mode mismatch to WARN while preserving the difference in the report.

## Recommended use

Typical campaign comparisons include:

```text
same host / firmware A  → firmware B
same host / SDK A       → SDK B
same device / code A    → code B
Windows campaign        → Linux campaign
MJPEG campaign          → YUYV campaign (explicit cross-mode interpretation)
repeat campaign A       → repeat campaign B
```

For a code change, prefer keeping hardware, firmware, SDK, host, selected mode, lighting/motion conditions, and test procedure fixed. The more provenance changes at once, the weaker the causal interpretation.

## Exit behavior

The campaign comparator follows the per-run comparator semantics:

```text
FAIL  → non-zero exit
WARN  → zero by default, non-zero with --fail-on-warn
PASS  → zero
```

This allows it to become a later lab/CI gate once stable physical baselines and explicit acceptance budgets exist.

Related: `ar0234-qualification-protocol.md`, `nori-live-characterization.md`, Issue #35, Issue #10.
