#!/usr/bin/env python3
"""Assemble a one-file PDF report for a sample.

Combines, on a single page:
  * crossNN classification — brain-tumor (Capper) AND pan-cancer models
  * MethyLYZR classification
  * Sturgeon CNS classification
  * Lamprey haematological-malignancy classification (type + family level)
  * standalone copy-number profile (rapidCNS2 cnvpytor called-segment plot)

Run with the system python3 (matplotlib + pandas). Missing inputs are annotated
on the page instead of aborting — the report reflects whatever tools ran.

Usage:
    make_report.py --sample S --out report.pdf \
        --crossnn <sample>_crossnn_top.tsv \
        --methylyzr MethyLYZR_<sample>.csv \
        --sturgeon <sample>_sturgeon_general.csv \
        --lamprey <sample>_lamprey.csv \
        --cnv <sample>.cnv_segments.png \
        [--cnv-manhattan <sample>_cnvpytor_100k.png] \
        [--raw-reads N] [--aligned-reads N] [--patient-id ID]
"""
import argparse
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

# crossNN model key -> human label
CROSSNN_MODELS = {
    "brain_tumor_Capper": "crossNN — brain tumour (Capper)",
    "pan_cancer": "crossNN — pan-cancer",
}
TOP_N = 5
CROSSNN_THRESHOLD = 0.2    # crossNN confidence guide/cutoff
DEFAULT_THRESHOLD = 0.6    # MethyLYZR confidence guide
STURGEON_THRESHOLD = 0.95  # Sturgeon confidence guide/cutoff
LAMPREY_THRESHOLD = 0.90   # Lamprey "diagnostic" cutoff (its own report uses 0.90)


def _bar(ax, title, labels, scores, threshold=DEFAULT_THRESHOLD):
    if not labels:
        ax.text(0.5, 0.5, "no data", ha="center", va="center",
                transform=ax.transAxes, color="#a23a30")
        ax.set_title(title, fontsize=9, loc="left")
        ax.set_xticks([])
        ax.set_yticks([])
        return
    colors = ["#2b6cb0" if v >= threshold else "#9aa0a6" for v in scores]
    ax.bar(range(len(labels)), scores, color=colors)
    ax.axhline(threshold, color="black", linestyle="--", linewidth=0.8)
    ax.set_ylim(0, 1)
    ax.set_title(title, fontsize=9, loc="left")
    ax.set_ylabel("score", fontsize=8)
    ax.set_xticks(range(len(labels)))
    # Some models (Sturgeon CNS classes) emit very long names; rotated 40° they
    # would hang far down and overplot the notes below. Truncate for display.
    shown = [l if len(l) <= 18 else l[:17] + "…" for l in labels]
    ax.set_xticklabels(shown, rotation=40, ha="right", fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    for sp in ("right", "top"):
        ax.spines[sp].set_visible(False)
    # annotate the top call
    ax.text(0, min(0.98, scores[0] + 0.03), f"{scores[0]:.2f}",
            fontsize=7, ha="center")


def crossnn_axis(ax, model_key, title, path):
    if not path or not os.path.exists(path):
        _bar(ax, title, [], [], threshold=CROSSNN_THRESHOLD)
        return
    df = pd.read_csv(path, sep="\t")
    sub = df[df["model"] == model_key].sort_values("rank").head(TOP_N)
    _bar(ax, title, list(sub["class"].astype(str)),
         list(sub["score"].astype(float)), threshold=CROSSNN_THRESHOLD)


def methylyzr_axis(ax, path):
    title = "MethyLYZR"
    if not path or not os.path.exists(path):
        _bar(ax, title, [], [])
        return
    df = pd.read_csv(path)
    # columns: Class, Posterior Probability (already sorted descending)
    cls_col = df.columns[0]
    prob_col = df.columns[1]
    sub = df.head(TOP_N)
    _bar(ax, title, list(sub[cls_col].astype(str)),
         list(sub[prob_col].astype(float)))


def sturgeon_axis(ax, path):
    title = "Sturgeon"
    if not path or not os.path.exists(path):
        _bar(ax, title, [], [])
        return
    # Sturgeon writes one row, wide: 'number_probes' + one column per class
    # (calibrated scores). Drop the bookkeeping columns and rank the classes.
    df = pd.read_csv(path)
    row = df.iloc[0]
    drop = [c for c in ("number_probes", "timestamp") if c in df.columns]
    scores = row.drop(labels=drop).astype(float).sort_values(ascending=False)
    scores = scores.head(TOP_N)
    _bar(ax, title, list(scores.index.astype(str)), list(scores.values),
         threshold=STURGEON_THRESHOLD)


def cnv_axis(ax, seg_png, manhattan_png):
    ax.set_title("Copy-number profile (cnvpytor read-depth dotplot)",
                 fontsize=9, loc="left")
    # Use the cnvpytor manhattan/dotplot PNG (_cnvpytor_100k.png); fall back to
    # the called-segment plot only if the dotplot is missing.
    png = manhattan_png if (manhattan_png and os.path.exists(manhattan_png)) else seg_png
    if png and os.path.exists(png):
        # aspect="auto" lets the image fill the whole panel (the bottom half of
        # the page) instead of shrinking to its native square-ish aspect ratio.
        ax.imshow(mpimg.imread(png), aspect="auto")
    else:
        ax.text(0.5, 0.5, "no copy-number data", ha="center", va="center",
                transform=ax.transAxes, color="#a23a30")
    ax.axis("off")


def _fmt_int(s):
    try:
        return f"{int(s):,}"
    except (ValueError, TypeError):
        return None


def _lamprey_report_path(csv_path):
    return os.path.splitext(csv_path)[0] + "_report.txt"


def read_lamprey_families(csv_path):
    """Family-level top predictions from Lamprey's <result>_report.txt, as
    [(label, prob)] — the CSV only carries the 86 type-level probabilities."""
    rep = _lamprey_report_path(csv_path or "")
    fams, in_block = [], False
    if not csv_path or not os.path.exists(rep):
        return fams
    with open(rep) as fh:
        for line in fh:
            if line.startswith("Top 3 predictions (family)"):
                in_block = True
                continue
            if in_block:
                line = line.strip()
                if not line:
                    break
                # "1. B-ALL                         95.30%"
                body = line.split(".", 1)[1].strip()
                label, pct = body.rsplit(None, 1)
                fams.append((label.strip(), float(pct.rstrip("%")) / 100))
    return fams


def lamprey_display_names(yaml_path):
    """Class key -> human-readable type name from Lamprey's
    classification_system.yaml (CSV columns are short keys like PAX5P80R)."""
    if not yaml_path or not os.path.exists(yaml_path):
        return {}
    try:
        import yaml
        with open(yaml_path) as fh:
            return (yaml.safe_load(fh).get("names") or {}).get("type") or {}
    except Exception:
        return {}


def lamprey_axes(ax_type, ax_fam, path, classes_yaml=""):
    """Type-level top-N (from the CSV) and family-level top-3 (from the report)."""
    if not path or not os.path.exists(path):
        _bar(ax_type, "Lamprey — haematological type", [], [],
             threshold=LAMPREY_THRESHOLD)
        _bar(ax_fam, "Lamprey — family", [], [], threshold=LAMPREY_THRESHOLD)
        return None
    row = pd.read_csv(path).iloc[0]
    n_probes = int(row["probes"]) if "probes" in row else None
    scores = row.drop(labels=[c for c in ("probes",) if c in row.index])
    scores = scores.astype(float).sort_values(ascending=False).head(TOP_N)
    title = "Lamprey — haem. type"
    if n_probes is not None:
        title += f" ({n_probes:,} probes)"
    names = lamprey_display_names(classes_yaml)
    _bar(ax_type, title, [str(names.get(k, k)) for k in scores.index],
         list(scores.values), threshold=LAMPREY_THRESHOLD)
    fams = read_lamprey_families(path)
    _bar(ax_fam, "Lamprey — family", [f for f, _ in fams], [v for _, v in fams],
         threshold=LAMPREY_THRESHOLD)
    return scores.index[0], float(scores.iloc[0]), fams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--crossnn", default="")
    ap.add_argument("--methylyzr", default="")
    ap.add_argument("--sturgeon", default="")
    ap.add_argument("--cnv", default="")
    ap.add_argument("--cnv-manhattan", dest="cnv_manhattan", default="")
    ap.add_argument("--lamprey", default="")
    ap.add_argument("--lamprey-classes", dest="lamprey_classes", default="",
                    help="Lamprey classification_system.yaml (display names)")
    ap.add_argument("--raw-reads", dest="raw_reads", default="")
    ap.add_argument("--aligned-reads", dest="aligned_reads", default="")
    ap.add_argument("--patient-id", dest="patient_id", default="")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
    fig.suptitle(f"Methylation classification report — {args.sample}",
                 fontsize=13, fontweight="bold", y=0.985)

    # --- header: internal patient ID field (fillable if left blank) ----------
    pid = (args.patient_id or "").strip()
    fig.text(0.09, 0.958,
             f"Internal patient ID:  {pid if pid else '_' * 34}",
             ha="left", fontsize=10, fontweight="bold")

    # --- header: read counts -------------------------------------------------
    raw = _fmt_int(args.raw_reads)
    aln = _fmt_int(args.aligned_reads)
    reads = f"Sample: {args.sample}"
    if raw is not None:
        reads += f"   ·   Raw reads: {raw}"
    if aln is not None:
        pct = ""
        try:
            if int(args.raw_reads) > 0:
                pct = f" ({100 * int(args.aligned_reads) / int(args.raw_reads):.1f}%)"
        except (ValueError, TypeError, ZeroDivisionError):
            pct = ""
        reads += f"   ·   Aligned (primary): {aln}{pct}"
    fig.text(0.09, 0.940, reads, ha="left", fontsize=8.5)

    fig.text(0.5, 0.923,
             f"Generated {datetime.now():%Y-%m-%d %H:%M}  ·  "
             "EXPERIMENTAL — research use only, not for diagnostic use",
             ha="center", fontsize=8, color="#a23a30")

    # Rows of classifier bars (crossNN x2 / MethyLYZR+Sturgeon / optional
    # Lamprey type+family), a notes block, then the CNV panel filling the rest.
    # Rows are placed explicitly on a fixed pitch: below each bar panel the
    # rotated, truncated class labels need ~0.075 of page height, which a
    # shared gridspec hspace cannot size reliably. Lamprey is opt-in: its row
    # is drawn only when --lamprey was passed, otherwise the CNV panel grows.
    BAR_H, LABEL_GAP = 0.085, 0.095
    next_top = [0.895]   # top of the next bar row (mutable for the closure)

    def bar_row():
        top = next_top[0]
        g = fig.add_gridspec(1, 2, wspace=0.25, left=0.09, right=0.95,
                             top=top, bottom=top - BAR_H)
        next_top[0] = top - BAR_H - LABEL_GAP
        return fig.add_subplot(g[0, 0]), fig.add_subplot(g[0, 1])

    ax_l, ax_r = bar_row()
    crossnn_axis(ax_l, "brain_tumor_Capper",
                 CROSSNN_MODELS["brain_tumor_Capper"], args.crossnn)
    crossnn_axis(ax_r, "pan_cancer", CROSSNN_MODELS["pan_cancer"], args.crossnn)
    ax_l, ax_r = bar_row()
    methylyzr_axis(ax_l, args.methylyzr)
    sturgeon_axis(ax_r, args.sturgeon)
    with_lamprey = bool(args.lamprey)
    if with_lamprey:
        ax_l, ax_r = bar_row()
        lamprey_axes(ax_l, ax_r, args.lamprey, args.lamprey_classes)

    notes = ("Score bars show the top 5 classes per model"
             + (" (Lamprey family: top 3)" if with_lamprey else "") + ".  "
             f"Dashed guide: crossNN {CROSSNN_THRESHOLD}, "
             f"MethyLYZR {DEFAULT_THRESHOLD}, Sturgeon {STURGEON_THRESHOLD}"
             + (f", Lamprey {LAMPREY_THRESHOLD}" if with_lamprey else "")
             + "\n(blue ≥ guide, grey < guide).  "
             "crossNN: NN methylation classifier (brain-tumour + pan-cancer).  "
             "MethyLYZR: EPIC-array emulation classifier.\n"
             "Sturgeon: CNS tumour classifier.  ")
    if with_lamprey:
        notes += ("Lamprey: haematological malignancy classifier (86 types, "
                  "no CNS tumour classes) — only\ninformative if "
                  "lymphoma/leukaemia is in the differential.  ")
    notes += ("Copy-number: cnvpytor read-depth dotplot (RD/CN per 100 kb bin).")
    notes_top = next_top[0] + LABEL_GAP - 0.08   # just under the last labels
    fig.text(0.09, notes_top, notes, va="top", ha="left", fontsize=7)

    # CNV panel fills the rest of the page below the notes (+ its title).
    gs_cnv = fig.add_gridspec(1, 1, left=0.09, right=0.95,
                              top=notes_top - 0.08, bottom=0.03)
    cnv_axis(fig.add_subplot(gs_cnv[0, 0]), args.cnv, args.cnv_manhattan)

    with PdfPages(args.out) as pdf:
        pdf.savefig(fig)
        plt.close(fig)
    print(f"  Report written: {args.out}")


if __name__ == "__main__":
    main()
