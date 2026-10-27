#!/usr/bin/env python3
"""crossNN classification step, run inside the crossNN python environment.

Invoked as a subprocess by pipelines.py so the heavy NN_model import stays out
of the GUI server process. Mirrors the classification cell of the production
crossnn/pipeline.ipynb notebook.

Writes two TSVs per sample:
  <out_prefix>_all_scores.tsv  – every class score, all models (full ranking)
  <out_prefix>_top.tsv         – top-N classes per model (quick summary)

Usage:
    python3 crossnn_predict.py <crossnn_repo> <annotated_bedmethyl> <sample> \
            <out_prefix> <top_n> name=path [name=path ...]
"""
import sys
import os
import csv


def _write(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["sample", "model", "rank", "class", "score", "n_features"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    if len(sys.argv) < 7:
        sys.exit("usage: crossnn_predict.py <repo> <annotated> <sample> "
                 "<out_prefix> <top_n> name=path [name=path ...]")

    repo, annotated, sample, out_prefix, top_n_s = sys.argv[1:6]
    top_n = int(top_n_s)
    models = {}
    for spec in sys.argv[6:]:
        name, _, path = spec.partition("=")
        models[name] = path

    sys.path.insert(0, repo)
    from NN_model import NN_classifier  # noqa: E402

    all_rows = []   # every class, every model
    top_rows = []   # top_n per model
    for model_name, model_path in models.items():
        print(f"  Loading model: {model_name}", flush=True)
        clf = NN_classifier(model_path)
        print(f"  Predicting ({model_name}) ...", flush=True)
        # predict returns ALL classes already sorted by score (descending)
        scores, labels, n_features = clf.predict_from_bedMethyl(annotated)
        for rank, (lbl, scr) in enumerate(zip(labels, scores), 1):
            row = {
                "sample": sample, "model": model_name, "rank": rank,
                "class": lbl, "score": f"{float(scr):.6f}", "n_features": n_features,
            }
            all_rows.append(row)
            if rank <= top_n:
                top_rows.append(row)
        print(f"  Top {min(5, top_n)} [{model_name}]:", flush=True)
        for r in [r for r in top_rows if r["model"] == model_name][:5]:
            print(f"    {r['rank']}. {r['class']}: {float(r['score']):.4f}", flush=True)

    all_path = f"{out_prefix}_all_scores.tsv"
    top_path = f"{out_prefix}_top.tsv"
    _write(all_path, all_rows)
    _write(top_path, top_rows)
    print(f"  Written: {top_path} ({len(top_rows)} rows) and "
          f"{all_path} ({len(all_rows)} rows)", flush=True)


if __name__ == "__main__":
    main()
