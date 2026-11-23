"""วัดผล OCR จากไฟล์ predictions.tsv (path<TAB>gt<TAB>pred) (ใช้ CPU)

ผลลัพธ์: exact match, character error rate และคู่ตัวอักษรที่อ่านสลับกันบ่อย
คู่ที่ได้ใช้แทนค่าเดาใน contracts/flock_contracts/plates.py (CONFUSABLE_PAIRS)

    python -m flock_train.eval_ocr runs/ocr/test_predictions.tsv --out runs/ocr/eval.json
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def align_substitutions(gt: str, pred: str) -> tuple[int, list[tuple[str, str]]]:
    """Levenshtein ปกติ คืนระยะทางและรายการคู่ (gt, pred) ที่ถูกแทนกัน"""
    n, m = len(gt), len(pred)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (gt[i - 1] != pred[j - 1]))
    subs = []
    i, j = n, m
    while i > 0 and j > 0:
        if d[i][j] == d[i - 1][j - 1] + (gt[i - 1] != pred[j - 1]):
            if gt[i - 1] != pred[j - 1]:
                subs.append((gt[i - 1], pred[j - 1]))
            i, j = i - 1, j - 1
        elif d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return d[n][m], subs


def evaluate(rows: list[tuple[str, str]]) -> dict:
    exact = 0
    edits = chars = 0
    pairs: Counter[tuple[str, str]] = Counter()
    for gt, pred in rows:
        exact += gt == pred
        dist, subs = align_substitutions(gt, pred)
        edits += dist
        chars += len(gt)
        for a, b in subs:
            pairs[tuple(sorted((a, b)))] += 1
    total = len(rows)
    return {
        "samples": total,
        "exact_match": exact / total if total else 0.0,
        "cer": edits / chars if chars else 0.0,
        "confusion_pairs": [{"pair": list(k), "count": v} for k, v in pairs.most_common()],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("predictions", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    with a.predictions.open(encoding="utf-8", newline="") as f:
        rows = [(r[1], r[2] if len(r) > 2 else "") for r in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE) if r]
    result = evaluate(rows)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("samples", "exact_match", "cer")}, indent=2))
    print("คู่ที่สลับบ่อย:", ", ".join(f"{x['pair'][0]}/{x['pair'][1]}×{x['count']}" for x in result["confusion_pairs"][:15]))


if __name__ == "__main__":
    main()
