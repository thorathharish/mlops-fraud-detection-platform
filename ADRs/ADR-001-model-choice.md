# ADR-001: Model Choice — XGBoost for Fraud Detection

**Status:** Accepted  
**Date:** 2026-06-21

## Context
Fraud detection requires high precision/recall on a severely imbalanced dataset (~1% fraud rate). The model must serve at p99 <100ms. We need explainability for compliance.

## Decision
Use **XGBoost** with `scale_pos_weight` to handle class imbalance.

## Rationale
| Option | PR-AUC | Latency | Explainability | Drift retraining cost |
|--------|--------|---------|---------------|----------------------|
| XGBoost | High | ~5ms | SHAP native | Low (minutes) |
| Neural Net (MLP) | High | ~10ms | Poor (LIME needed) | High (GPU hours) |
| Logistic Regression | Medium | ~1ms | Native | Very Low |
| Random Forest | Medium-High | ~20ms | SHAP | Low |

XGBoost wins on the latency + PR-AUC + retrainability triad. For a drift-triggered pipeline that retrains every few hours, low retraining cost is critical.

## `scale_pos_weight` rationale
With 99:1 class ratio, `scale_pos_weight = 99` — XGBoost weights each fraud sample 99× more, equivalent to oversampling without the memory cost. Alternative (SMOTE) was tested but added preprocessing complexity with no PR-AUC gain.

## Consequences
- Model is not neural — misses deep feature interactions (acceptable for tabular fraud data).
- Retraining < 5 minutes on CPU, fits easily in GitHub Actions free tier.
- SHAP values available for per-prediction explainability if required by compliance.
