# ADR-003: Feature Store — Feast + Redis

**Status:** Accepted  
**Date:** 2026-06-21

## Context
Fraud scoring requires pre-computed features (e.g. velocity in last 1h, avg spend over 7d) that are expensive to compute at inference time. We need a low-latency online store.

## Decision
Use **Feast** as the feature store with **Redis** as the online store backend.

## Rationale
| Option | Latency | Consistency | Operational cost |
|--------|---------|-------------|-----------------|
| Feast + Redis (chosen) | <2ms | Point-in-time correct | Low (Redis in cluster) |
| Direct DB lookup (Postgres) | ~10ms | Consistent | Medium |
| In-process cache (dict) | <1ms | Stale | High (memory, no sharing) |
| Tecton / Vertex Feature Store | <2ms | High | Very High ($) |

Feast is open-source, GCP-native (integrates with BigQuery offline store), and Redis gives sub-2ms online serving. Vertex AI Feature Store was considered but costs ~$200/month for the managed version — unacceptable for a portfolio project targeting ~$0 GCP spend.

## Architecture
- **Offline store** (training): local Parquet files / GCS + DVC  
- **Online store** (inference): Redis (local) → Redis in cluster  
- **Feast `feast materialize`**: scheduled job that syncs offline → online every hour

## Consequences
- Requires Redis running alongside the serving container.
- Features must be pre-materialized — cold-start penalty on cluster restart.
- Point-in-time correctness: training uses historical snapshots, avoiding leakage.
