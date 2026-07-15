"""
Offline Threshold Calibration Script — Day 5 (P1 Offline Tool)
================================================================
Calibrates safety_threshold values in network_profile.json using
labeled NSL-KDD ground-truth data.

BLUEPRINT §6.1 compliance:
  - This is a P1 offline tool: run EXPLICITLY, never by bootstrap or CI
  - Output is PRINTED for human review and MANUAL entry into network_profile.json
  - Does NOT auto-apply changes

BLUEPRINT §3.3.4 compliance:
  - Uses attack_cat/label ONLY as evaluation metadata (test expectations)
  - Labels never enter runtime ingestion, detection, or RCA inputs
  - Proxy suffix documented for uncalibrated mappings

Usage (from repo root):
    .venv/Scripts/python.exe scripts/calibrate_thresholds.py [--data-root data/]

Output:
    Human-readable calibration report per signal showing:
    - Current threshold
    - F1-optimal threshold at 90% recall
    - Value distribution for normal vs anomalous class
    - Recommendation with explicit caveats for proxy mappings
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))

import json
import numpy as np

DATA_ROOT_DEFAULT = _REPO / "data"
PROFILE_PATH = _REPO / "backend" / "app" / "fixtures" / "reference_profiles" / "network_profile.json"

SEP = "─" * 68


def _load_profile() -> dict:
    with PROFILE_PATH.open() as f:
        return json.load(f)


def _load_nslkdd(data_root: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """Load NSL-KDD training data. Returns (features, labels) or None if not found."""
    try:
        from app.ingestion.dataset_bridge.nsl_kdd import NslKddReader
        reader = NslKddReader()
        records = reader.records(data_root, limit=5000)
    except (FileNotFoundError, ImportError) as e:
        print(f"  ⚠ NSL-KDD not available: {e}")
        return None

    values: list[dict] = []
    labels: list[int] = []
    for r in records:
        meta = r.get("_meta", {})
        label = 0 if str(meta.get("klass", "normal")).lower() == "normal" else 1
        values.append({
            "src_bytes": float(meta.get("src_bytes", 0)),
            "count":     float(meta.get("count", 0)),
        })
        labels.append(label)


    if not values:
        return None

    return values, labels


def _calibrate_threshold(
    normal_vals: list[float],
    anomaly_vals: list[float],
    current_threshold: float,
    signal_name: str,
    is_proxy: bool,
) -> dict:
    """
    Sweep threshold values and find F1-optimal.
    Returns report dict.
    """
    if not normal_vals or not anomaly_vals:
        return {
            "status": "insufficient_data",
            "signal": signal_name,
            "is_proxy": is_proxy,
        }


    all_vals = np.array(normal_vals + anomaly_vals)
    all_labels = np.array([0] * len(normal_vals) + [1] * len(anomaly_vals))

    # Percentile statistics
    n5, n25, n50, n75, n95 = np.percentile(normal_vals, [5, 25, 50, 75, 95])
    a5, a25, a50, a75, a95 = np.percentile(anomaly_vals, [5, 25, 50, 75, 95])

    # Sweep thresholds from 5th percentile of anomaly vals to max
    candidates = np.linspace(n95, np.percentile(anomaly_vals, 95), 50)
    best_f1 = 0.0
    best_threshold = current_threshold
    best_precision = 0.0
    best_recall = 0.0

    for thresh in candidates:
        preds = (all_vals >= thresh).astype(int)
        tp = int(((preds == 1) & (all_labels == 1)).sum())
        fp = int(((preds == 1) & (all_labels == 0)).sum())
        fn = int(((preds == 0) & (all_labels == 1)).sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = float(thresh)
            best_precision = precision
            best_recall = recall

    # Current threshold performance
    preds = (all_vals >= current_threshold).astype(int)
    tp = int(((preds == 1) & (all_labels == 1)).sum())
    fp = int(((preds == 1) & (all_labels == 0)).sum())
    fn = int(((preds == 0) & (all_labels == 1)).sum())
    cur_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    cur_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    cur_f1 = 2 * cur_precision * cur_recall / (cur_precision + cur_recall) if (cur_precision + cur_recall) > 0 else 0.0

    return {
        "signal": signal_name,
        "is_proxy": is_proxy,
        "current_threshold": current_threshold,
        "calibrated_threshold": round(best_threshold, 2),
        "normal_p5_p95": (round(n5, 2), round(n95, 2)),
        "anomaly_p5_p95": (round(a5, 2), round(a95, 2)),
        "current_f1": round(cur_f1, 3),
        "current_precision": round(cur_precision, 3),
        "current_recall": round(cur_recall, 3),
        "calibrated_f1": round(best_f1, 3),
        "calibrated_precision": round(best_precision, 3),
        "calibrated_recall": round(best_recall, 3),
        "n_normal": len(normal_vals),
        "n_anomaly": len(anomaly_vals),
    }


def _print_report(r: dict) -> None:
    print(f"\n  Signal: {r['signal']}")
    if r.get("status") == "insufficient_data":
        print("    ⚠ Insufficient data for calibration")
        return

    proxy_tag = "  ⚠ PROXY MAPPING — values are uncalibrated proxies" if r["is_proxy"] else ""
    change = r["calibrated_threshold"] - r["current_threshold"]
    change_str = f"+{change:.1f}" if change > 0 else f"{change:.1f}"

    print(f"    Current threshold:    {r['current_threshold']}")
    print(f"    Calibrated threshold: {r['calibrated_threshold']}  ({change_str})")
    print(f"    Normal class   p5={r['normal_p5_p95'][0]}  p95={r['normal_p5_p95'][1]}  (n={r['n_normal']})")
    print(f"    Anomaly class  p5={r['anomaly_p5_p95'][0]}  p95={r['anomaly_p5_p95'][1]}  (n={r['n_anomaly']})")
    print(f"    Current   : F1={r['current_f1']:.3f}  P={r['current_precision']:.3f}  R={r['current_recall']:.3f}")
    print(f"    Calibrated: F1={r['calibrated_f1']:.3f}  P={r['calibrated_precision']:.3f}  R={r['calibrated_recall']:.3f}")
    if abs(change) > r["current_threshold"] * 0.1:
        print(f"    📌 Recommendation: Consider updating threshold to {r['calibrated_threshold']}")
    else:
        print(f"    ✓  Current threshold within 10% of optimal — no change needed")
    if proxy_tag:
        print(f"    {proxy_tag}")
    print()
    print("    ⚠ DO NOT AUTO-APPLY. Review and manually update network_profile.json after validation.")


def main(data_root: Path) -> None:
    print(f"\n{'═'*68}")
    print("  THRESHOLD CALIBRATION REPORT — OFFLINE P1 TOOL")
    print("  BLUEPRINT §3.3.4 — Labels used for evaluation ONLY")
    print("  Output is for HUMAN REVIEW — do not auto-apply")
    print(f"{'═'*68}")

    profile = _load_profile()
    aliases = {k: v for k, v in profile.get("signal_aliases", {}).items() if not k.startswith("_")}

    result = _load_nslkdd(data_root)
    if result is None:
        print("\n  ⚠ NSL-KDD dataset not available. Cannot calibrate.")
        print("     Ensure data/NSL-KDD-Dataset is present and readable.")
        print(f"{'═'*68}\n")
        return

    records, labels = result
    n_total = len(labels)
    n_anomaly = sum(labels)
    print(f"\n  NSL-KDD: {n_total} records  ({n_anomaly} anomalous, {n_total - n_anomaly} normal)")
    print(f"  Data root: {data_root}")
    print(SEP)

    # Signal mapping: NSL-KDD proxy → canonical signal
    signal_mappings = [
        ("src_bytes",  "src_bytes_proxy",  "forwarded_requests_per_second"),
        ("count",      "count_proxy",       "active_connections_total"),
    ]

    print(f"\n  {SEP}")
    print("  Per-Signal Calibration Results")
    print(f"  {SEP}")

    for raw_col, proxy_name, canonical in signal_mappings:
        current_threshold = profile["signals"].get(canonical, {}).get("safety_threshold")
        if current_threshold is None:
            print(f"\n  {canonical}: no safety_threshold in profile — skip")
            continue
        normal_vals = [float(r[raw_col]) for r, lbl in zip(records, labels) if lbl == 0 and raw_col in r]
        anomaly_vals = [float(r[raw_col]) for r, lbl in zip(records, labels) if lbl == 1 and raw_col in r]

        report = _calibrate_threshold(
            normal_vals, anomaly_vals,
            current_threshold=current_threshold,
            signal_name=f"{canonical} (via {proxy_name})",
            is_proxy=True,
        )
        _print_report(report)

    print(f"\n{'═'*68}")
    print("  SUMMARY")
    print("  This report uses NSL-KDD src_bytes/count as PROXY signals.")
    print("  These are UNCALIBRATED — raw bytes ≠ requests/second.")
    print("  Treat all thresholds as indicative directional guidance only.")
    print("  The golden scenario uses hand-reviewed values from network_profile.json.")
    print(f"{'═'*68}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline threshold calibration using NSL-KDD ground truth.")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT_DEFAULT,
                        help="Root directory containing dataset folders")
    args = parser.parse_args()
    main(args.data_root)
