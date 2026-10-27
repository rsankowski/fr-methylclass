#!/usr/bin/env python3
"""Genome-wide CNV segment plot from a cnvpytor `-call` TSV.

The default cnvpytor `manhattan` view is a per-bin read-depth scatter that is
mean-normalised to CN=2 per sample; across low/medium-coverage samples it is
dominated by shared mappability noise, so every sample's plot looks like the
same diploid cloud even when the underlying calls differ. This script instead
draws the *called* segments as horizontal copy-number levels over a genome
ideogram axis, so each sample's gains/losses are immediately visible and
distinct.

Usage:
    cnv_segment_plot.py <calls.tsv> <id> <out.png> <genome.fai>
"""
import sys
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

CHROMS = [f"chr{c}" for c in list(range(1, 23)) + ["X", "Y"]]


def load_sizes(fai):
    sizes = {}
    with open(fai) as fh:
        for line in fh:
            f = line.split("\t")
            if f[0] in CHROMS:
                sizes[f[0]] = int(f[1])
    return sizes


def main():
    calls, sample, out_png, fai = sys.argv[1:5]
    sizes = load_sizes(fai)
    chroms = [c for c in CHROMS if c in sizes]

    # cumulative genome offsets for a single linear x-axis
    offset, offsets, total = {}, {}, 0
    for c in chroms:
        offset[c] = total
        total += sizes[c]
    centers = {c: offset[c] + sizes[c] / 2 for c in chroms}

    fig, ax = plt.subplots(figsize=(14, 4))
    # diploid baseline + alternating chromosome shading
    ax.axhline(2, color="grey", lw=0.6, ls="--", zorder=1)
    for i, c in enumerate(chroms):
        if i % 2:
            ax.axvspan(offset[c], offset[c] + sizes[c], color="0.96", zorder=0)

    rx = re.compile(r"(chr[\w]+):(\d+)-(\d+)")
    n = 0
    with open(calls) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 4:
                continue
            m = rx.match(f[1])
            if not m or m.group(1) not in offset:
                continue
            chrom, start, end = m.group(1), int(m.group(2)), int(m.group(3))
            level = float(f[3])
            x0, x1 = offset[chrom] + start, offset[chrom] + end
            color = "firebrick" if level > 2 else "navy"
            ax.hlines(level, x0, x1, color=color, lw=3, zorder=3)
            n += 1

    ax.set_xticks([centers[c] for c in chroms])
    ax.set_xticklabels([c.replace("chr", "") for c in chroms], fontsize=7)
    ax.set_xlim(0, total)
    ax.set_ylim(0, 4)
    ax.set_ylabel("Copy number (cnvpytor RD level)")
    ax.set_title(f"{sample} — CNV segments ({n} calls)")
    ax.legend(handles=[Line2D([0], [0], color="firebrick", lw=3, label="gain"),
                       Line2D([0], [0], color="navy", lw=3, label="loss")],
              loc="upper right", fontsize=7, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)


if __name__ == "__main__":
    main()
