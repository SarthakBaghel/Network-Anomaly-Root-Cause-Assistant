import sys; sys.path.insert(0,'backend')
from app.config import settings
from app.ingestion.catalogue import detector_rules
from app.detection.rolling_zscore import ANOMALY_TYPES, STATIC_ONLY_SIGNALS

d = detector_rules()
thresholds = d.get('safety_thresholds', {})
log_rules = d.get('log_rules', [])

print('=== CURRENT DETECTION STATE AUDIT ===')
print(f'Monitored metric signals:        {len(thresholds)}')
print(f'Static-only signals:             {STATIC_ONLY_SIGNALS}')
print(f'Log rule patterns in catalogue:  {len(log_rules)}')
print(f'Min baseline points required:    {settings.detector_min_baseline_points}')
print(f'Detection window:                {settings.detector_window_seconds}s')
print(f'Z-score threshold to fire:       {settings.metric_zscore_threshold}')
print(f'Anomaly score to create record:  {settings.anomaly_threshold}')
print()
print('Signal thresholds:')
for k,v in thresholds.items():
    print(f'  {k:<45} threshold={v}')
print()
print('Log rule event codes:')
for r in log_rules:
    print(f'  {r["event_code"]:<35} score={r["anomaly_score"]}  repeatable={r.get("repeatable")}')
