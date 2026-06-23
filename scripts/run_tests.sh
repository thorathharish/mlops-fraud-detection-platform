#!/usr/bin/env bash
# FraudGuard end-to-end test runner
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0

check() {
    local label="$1" result="$2" detail="${3:-}"
    if [ "$result" = "ok" ]; then
        printf "  \033[32m[PASS]\033[0m %s %s\n" "$label" "$detail"
        PASS=$((PASS+1))
    else
        printf "  \033[31m[FAIL]\033[0m %s %s\n" "$label" "$detail"
        FAIL=$((FAIL+1))
    fi
}

echo "============================================"
echo "   FRAUDGUARD END-TO-END TEST SUITE"
echo "============================================"

# ── 1. MLflow ──────────────────────────────────────────────────────────
echo ""
echo "[1] MLflow Tracking Server (port 5000)"
code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/ 2>/dev/null || echo 000)
check "MLflow reachable" "$([ "$code" = "200" ] && echo ok || echo fail)" "HTTP $code"

model_info=$(MLFLOW_TRACKING_URI=http://localhost:5000 python -c "
from mlflow.tracking import MlflowClient
c = MlflowClient()
v = max(c.search_model_versions(\"name='fraudguard-xgboost'\"), key=lambda x: int(x.version))
aliases = list(c.get_registered_model('fraudguard-xgboost').aliases.keys())
print(f'v{v.version} aliases={aliases} status={v.status}')
" 2>/dev/null || echo "error")
check "Model registered + aliased" "$(echo "$model_info" | grep -q production && echo ok || echo fail)" "$model_info"

# ── 2. FastAPI Serving ─────────────────────────────────────────────────
echo ""
echo "[2] FastAPI Serving (port 8000)"

health=$(curl -s http://localhost:8000/health 2>/dev/null || echo "{}")
h_status=$(echo "$health" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','fail'))" 2>/dev/null || echo fail)
check "Health endpoint ok" "$([ "$h_status" = "ok" ] && echo ok || echo fail)" "$health"

# Legit transaction
legit_resp=$(curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"transaction_id":"test_legit","amount":35.0,"hour_of_day":10,"day_of_week":1,"merchant_category":2,"distance_from_home_km":3.0,"velocity_1h":1,"velocity_24h":3,"avg_spend_7d":50.0,"is_international":0,"card_present":1}' \
  2>/dev/null || echo "{}")
legit_d=$(echo "$legit_resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('decision','?'),d.get('fraud_probability',0),d.get('latency_ms',0))" 2>/dev/null || echo "? 0 0")
legit_decision=$(echo $legit_d | cut -d' ' -f1)
legit_score=$(echo $legit_d | cut -d' ' -f2)
legit_lat=$(echo $legit_d | cut -d' ' -f3)
check "Legit txn -> ALLOW" "$([ "$legit_decision" = "ALLOW" ] && echo ok || echo fail)" "score=$legit_score  latency=${legit_lat}ms"

# Fraud transaction
fraud_resp=$(curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"transaction_id":"test_fraud","amount":9850.0,"hour_of_day":2,"day_of_week":6,"merchant_category":11,"distance_from_home_km":450.0,"velocity_1h":9,"velocity_24h":28,"avg_spend_7d":55.0,"is_international":1,"card_present":0}' \
  2>/dev/null || echo "{}")
fraud_d=$(echo "$fraud_resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('decision','?'),d.get('fraud_probability',0),d.get('latency_ms',0))" 2>/dev/null || echo "? 0 0")
fraud_decision=$(echo $fraud_d | cut -d' ' -f1)
fraud_score=$(echo $fraud_d | cut -d' ' -f2)
fraud_lat=$(echo $fraud_d | cut -d' ' -f3)
check "Fraud txn -> BLOCK" "$([ "$fraud_decision" = "BLOCK" ] && echo ok || echo fail)" "score=$fraud_score  latency=${fraud_lat}ms"

# Invalid payload
invalid_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" -d '{"amount":-1}' 2>/dev/null || echo 000)
check "Invalid payload -> 422" "$([ "$invalid_code" = "422" ] && echo ok || echo fail)" "HTTP $invalid_code"

# Prometheus metrics
met=$(curl -s http://localhost:8000/metrics 2>/dev/null || echo "")
check "Prometheus /metrics exposed" "$(echo "$met" | grep -q fraudguard_requests_total && echo ok || echo fail)" "metrics endpoint"

docs=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs 2>/dev/null || echo 000)
check "Swagger /docs" "$([ "$docs" = "200" ] && echo ok || echo fail)" "HTTP $docs"

# ── 3. Batch predictions ───────────────────────────────────────────────
echo ""
echo "[3] Batch Prediction (10 transactions)"

amounts=(25.0 8500.0 120.0 6700.0 55.0 3200.0 80.0 9100.0 42.0 7800.0)
hours=(14 2 11 3 9 1 15 23 12 4)
intl=(0 1 0 1 0 1 0 1 0 1)
vel1h=(1 8 1 7 2 6 1 10 1 9)
vel24h=(3 25 5 20 6 18 4 30 2 22)

block_count=0; allow_count=0
for i in 0 1 2 3 4 5 6 7 8 9; do
    id="batch_$((i+1))"
    body="{\"transaction_id\":\"$id\",\"amount\":${amounts[$i]},\"hour_of_day\":${hours[$i]},\"day_of_week\":2,\"merchant_category\":5,\"distance_from_home_km\":100.0,\"velocity_1h\":${vel1h[$i]},\"velocity_24h\":${vel24h[$i]},\"avg_spend_7d\":60.0,\"is_international\":${intl[$i]},\"card_present\":0}"
    resp=$(curl -s -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d "$body" 2>/dev/null || echo "{}")
    parsed=$(echo "$resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('decision','?'),d.get('fraud_probability',0),d.get('latency_ms',0))" 2>/dev/null || echo "? 0 0")
    dec=$(echo $parsed | cut -d' ' -f1)
    sc=$(echo $parsed | cut -d' ' -f2)
    lat=$(echo $parsed | cut -d' ' -f3)
    printf "    %-10s  amount=%-8s  score=%-6s  -> %-5s  (%sms)\n" "$id" "${amounts[$i]}" "$sc" "$dec" "$lat"
    [ "$dec" = "BLOCK" ] && block_count=$((block_count+1)) || allow_count=$((allow_count+1))
done
check "All 10 batch predictions returned" "$([ $((block_count+allow_count)) -eq 10 ] && echo ok || echo fail)" "$allow_count ALLOW / $block_count BLOCK"

# ── 4. Prometheus ──────────────────────────────────────────────────────
echo ""
echo "[4] Prometheus (port 9090)"
prom=$(curl -s http://localhost:9092/-/healthy 2>/dev/null || echo "")
check "Prometheus healthy" "$(echo "$prom" | grep -qi healthy && echo ok || echo fail)" "$prom"

prom_data=$(curl -s "http://localhost:9092/api/v1/query?query=fraudguard_requests_total" 2>/dev/null || echo "{}")
prom_ok=$(echo "$prom_data" | python -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print('ok' if r else 'fail')" 2>/dev/null || echo fail)
total=$(echo "$prom_data" | python -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(int(sum(float(x['value'][1]) for x in r)))" 2>/dev/null || echo 0)
check "fraudguard metrics in Prometheus" "$prom_ok" "$total requests tracked"

# ── 5. Drift Detection ─────────────────────────────────────────────────
echo ""
echo "[5] Evidently Drift Detection"
set +e
python src/monitoring/drift_detector.py > /tmp/drift_out.txt 2>&1
drift_exit=$?
set -e
drift_line=$(grep "Drifted [0-9]" /tmp/drift_out.txt | head -1 || echo "")
feat_line=$(grep "Drifted features" /tmp/drift_out.txt | head -1 || echo "")
check "Drift detected (exit=1)" "$([ $drift_exit -eq 1 ] && echo ok || echo fail)" "$drift_line"
check "Drift report HTML generated" "$([ -f reports/drift_report.html ] && echo ok || echo fail)" "reports/drift_report.html"
n_drifted=$(python -c "import json; d=json.load(open('reports/drift_summary.json')); print(d['n_drifted_features'])" 2>/dev/null || echo 0)
check "6 features flagged" "$([ "$n_drifted" = "6" ] && echo ok || echo fail)" "$feat_line"

# ── 6. Unit Tests ──────────────────────────────────────────────────────
echo ""
echo "[6] Pytest Unit Tests"
test_out=$(python -m pytest tests/ -q 2>&1)
passed=$(echo "$test_out" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
echo "$test_out" | tail -3
check "All unit tests pass" "$([ "$passed" = "10" ] && echo ok || echo fail)" "$passed/10 passed"

# ── 7. MLflow experiment ───────────────────────────────────────────────
echo ""
echo "[7] MLflow Experiment Metrics"
mlflow_out=$(MLFLOW_TRACKING_URI=http://localhost:5000 python -c "
from mlflow.tracking import MlflowClient
c = MlflowClient()
runs = c.search_runs(['1'], order_by=['metrics.val_pr_auc DESC'], max_results=1)
r = runs[0]
m = r.data.metrics
print(f\"pr_auc={m.get('val_pr_auc',0):.4f}  roc_auc={m.get('val_roc_auc',0):.4f}  f1={m.get('val_f1',0):.4f}\")
" 2>/dev/null || echo "error")
check "MLflow metrics logged" "$(echo "$mlflow_out" | grep -q pr_auc && echo ok || echo fail)" "$mlflow_out"

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "============================================"
if [ $FAIL -eq 0 ]; then
    printf "  \033[32mRESULTS: %d PASSED  |  %d FAILED\033[0m\n" $PASS $FAIL
else
    printf "  \033[33mRESULTS: %d PASSED  |  %d FAILED\033[0m\n" $PASS $FAIL
fi
echo "============================================"
echo ""
echo "Services running:"
echo "  API:        http://localhost:8000/docs"
echo "  MLflow UI:  http://localhost:5000"
echo "  Prometheus: http://localhost:9092"
[ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/ 2>/dev/null)" = "200" ] && echo "  Grafana:    http://localhost:3000  (admin/admin)" || echo "  Grafana:    http://localhost:3000  (starting...)"
