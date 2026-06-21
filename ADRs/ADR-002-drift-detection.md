# ADR-002: Drift Detection Strategy — Evidently + Feature Distribution

**Status:** Accepted  
**Date:** 2026-06-21

## Context
Fraud patterns shift over time (new attack vectors, seasonal behaviour). We need automated detection to avoid serving a stale model weeks after distribution shift.

## Decision
Use **Evidently** for feature distribution drift, comparing live inference data against a reference snapshot from training time. Trigger retrain when >30% of features drift.

## Rationale
| Option | What it detects | Latency | Setup complexity |
|--------|----------------|---------|-----------------|
| Evidently (chosen) | Feature + prediction drift | Batch | Low |
| PSI per feature | Input distribution shift | Batch | Medium |
| Model performance monitor | Label drift (needs ground truth) | Delayed | High |
| Alibi Detect | Statistical tests, concept drift | Batch/online | High |

Evidently provides HTML reports (good for demos), JSON output (good for CI/CD gates), and covers both feature and prediction drift in one pass. Ground-truth labels for fraud arrive with days of delay — feature drift is the practical early warning signal.

## Threshold choice: 30%
- < 20%: too sensitive, retrains on noise
- > 50%: too late, model degrades significantly
- 30% with 6-hour checks balances freshness vs compute cost

## Consequences
- Requires storing a reference snapshot in GCS (done via DVC).
- Cannot detect concept drift directly — mitigated by also monitoring prediction score distribution.
- False positives possible (e.g. holiday spending spike). Accepted: retrain is cheap.
