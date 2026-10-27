# fr-methylclass

Nanopore methylation-based tumour classification as a Nextflow pipeline.

> ⚠️ **EXPERIMENTAL. RESEARCH USE ONLY.** None of the classifiers are validated for diagnostic use.

fr-methylclass runs several published methylation classifiers (crossNN, MethyLYZR,
Sturgeon, Lamprey) plus copy-number profiling on nanopore BAMs with 5mC calls, and
writes a one-page PDF report per sample. It is the Nextflow (DSL2) port of the
Methylation Classification GUI used in Freiburg. Every path, model and parameter
is a pipeline parameter, and every tool runs in a pinned container.

```
BAMs ─► discover + group ─► ALIGN (merge fragments → dorado aligner → sort/index), once per sample × genome
                              ├─ hg19 ─► modkit pileup --combine-mods ─► bedtools ∩ probes ─► crossNN (Capper + pan-cancer)
                              ├─ hg38 ─► chr shards ─► bam2feather ─► MethyLYZR
                              ├─ hg38 ─► modkit pileup ─► sturgeon inputtobed ─► sturgeon predict
                              ├─ hg38 ─► lamprey-preprocess ─► lamprey                    (opt-in)
                              ├─ hg38 ─► cnvpytor 100 kb ─► CNV segment plot
                              └─ hg38 ─► rapidCNS2 (nested Nextflow run)                 (opt-in)
             raw reads ─► merge ─► EPI2ME wf-metagenomics (nested Nextflow run)          (opt-in)
             all of the above ─► one-page PDF report per sample
```

## Quick start

```bash
git clone https://github.com/rsankowski/fr-methylclass.git

# 1. Build the classifier images locally (their licences forbid redistribution, see below)
fr-methylclass/containers/build.sh crossnn methylyzr sturgeon lamprey

# 2. Fetch the models (crossNN, MethyLYZR, Sturgeon, Lamprey), about 10 GB
fr-methylclass/scripts/download_assets.sh /data/methylclass-assets

# 3. Run (Nextflow pulls the pipeline from GitHub; hts/align/report images come from ghcr.io)
nextflow run rsankowski/fr-methylclass -r v1.0.0 -profile docker \
    --input /data/run42/bam_pass \
    --hg19_fasta /ref/hg19.fa --hg38_fasta /ref/hg38.fa \
    --assets_dir /data/methylclass-assets \
    --outdir /data/run42/methylclass
```

Requirements: Nextflow ≥ 24.04, Java 17+, and Docker, Podman, Singularity or
Apptainer. A GPU is optional (`-profile docker,gpu` speeds up alignment).

Check the installation with dummy data (no models or references needed):

```bash
nextflow run rsankowski/fr-methylclass -r v1.0.0 -profile test,docker -stub-run
```

On the Freiburg workstation, the tools are already installed natively:

```bash
nextflow run main.nf -profile host --input /path/to/bam_pass --outdir results
```

## Input

`--input` takes a comma-separated list of any of these:

| Input | Becomes |
|---|---|
| a `.bam` file | one sample, named after the file |
| a folder (searched recursively) | with `--group_by folder` (the default), one sample per parent directory, and its fragments are merged. This is ONT's `bam_pass/<barcode>/*.bam` layout. With `--group_by file`, each BAM is one sample. |
| a `.csv` with columns `sample,bam` | explicit mapping. Several rows with the same sample are merged. |

The input BAMs must be dorado/MinKNOW BAMs with 5mC calls. They need the `MM`/`ML`
tags, and MethyLYZR's `bam2feather` also reads the `@RG` header (`DT`) and the
per-read `st` start time. Raw `bam_pass` output has all of these.

The pipeline aligns unaligned (basecalled) BAMs with `dorado aligner`, which keeps
the MM/ML tags. A single BAM that is already aligned (its header has `@SQ`) is
only sorted and indexed. The pipeline aligns each sample once per genome, and
every tool that uses that genome shares the alignment.

## Tools

`--tools` defaults to `crossnn,methylyzr,sturgeon,cnv,report`, the same set the
GUI ticks by default. To add more, list them, e.g.
`--tools crossnn,methylyzr,sturgeon,lamprey,cnv,report`, or use `--tools all`.

| Tool | Genome | Assets (`--assets_dir` layout, or the explicit param) |
|---|---|---|
| `crossnn` | hg19 | `crossnn/Capper_et_al_NN.pkl` (`--crossnn_model_capper`), `crossnn/pancan_devel_v5i_NN.pkl` (`--crossnn_model_pancan`); probe BED shipped in `assets/nf/` |
| `methylyzr` | hg38 | `methylyzr/{EPIC_CpGannotation.bed, betas_mean.feather, W_RELIEF.feather, class_priors.csv}` |
| `sturgeon` | hg38 | `sturgeon/general.zip` (`--sturgeon_model`) |
| `lamprey` | hg38 | `lamprey/model/` = HF snapshot of `tachterberg/Lamprey` rev `6167d763` (`--lamprey_model`). This can also be a path inside a HF cache (`…/models--tachterberg--Lamprey/snapshots/<rev>`), in which case the whole repo dir is staged so its blob symlinks resolve. A repo id here downloads the model at run time instead. |
| `cnv` | hg38 | none (cnvpytor in the rapidCNS2 image) |
| `rapidcns2` | hg38 | `--annovar_path --annovar_db --annotsv_annot --rapidcns2_annotations --rapidcns2_cnv_genes --rapidcns2_panel` |
| `metagenomics` | raw reads | none. Needs internet on first run (`--metagenomics_database_set`, `--metagenomics_classifier`). |
| `report` | n/a | none |

You can change the genome of each tool with `--<tool>_genome hg19|hg38`. If a
FASTA has no `.fai`, the pipeline creates one.

**rapidCNS2 and metagenomics** are full Nextflow pipelines of their own. They
are launched as one task on the host, so they need `nextflow` and Docker
available there. Each sample gets a persistent launch/work directory under
`--nested_workdir` and is started with `-resume`, so a rerun after a failure
reuses that sample's finished tasks. With `--rapidcns2_pipeline`, you can point
at a local (patched) checkout instead of `areebapatel/Rapid-CNS2_nf`.

## Output

The output has the same layout as the GUI's:

```
<outdir>/aligned/<genome>/<sample>/<sample>.sorted.bam(.bai)
<outdir>/crossnn/bedmethyl/  <outdir>/crossnn/results/<sample>_crossnn_{top,all_scores}.tsv
<outdir>/methylyzr/feather/  <outdir>/methylyzr/results/MethyLYZR_<sample>.{csv,pdf}
<outdir>/sturgeon/bedmethyl/ <outdir>/sturgeon/results/<sample>/
<outdir>/lamprey/preprocessed/ <outdir>/lamprey/results/<sample>_lamprey{.csv,_report.txt,_top5.png}
<outdir>/cnv/<sample>.cnvpytor.calls.100000.tsv  <sample>.cnv_segments.png  <sample>_cnvpytor_100k.png
<outdir>/rapidcns2/results-<sample>/
<outdir>/metagenomics/results-<sample>/
<outdir>/report/<sample>_report.pdf
<outdir>/pipeline_info/   (Nextflow timeline / report / trace)
```

If one tool fails for a sample, the other tools still run (`--continue_on_error
true`, the default, matching the GUI). The PDF then shows "no data" for the
failed tool. Use `--continue_on_error false` to stop on the first error.

## Profiles

| Profile | Use |
|---|---|
| `docker` / `podman` | images from `--container_registry` (default `ghcr.io/rsankowski`) |
| `singularity` / `apptainer` | the same images via `docker://`. Build the classifier images into a private registry you control and set `--restricted_registry` to it. |
| `gpu` | passes the GPU into the dorado container (`--gpus all` / `--nv`) |
| `slurm` | SLURM executor. Combine it with a container profile. |
| `host` | native tools at the paths in `conf/host.config` (this workstation). Copy and edit it for another machine. |
| `test` | wiring check with dummy files: `nextflow run main.nf -profile test -stub-run` |

Resources are set per process label in `conf/base.config` and capped by
`--max_cpus`, `--max_memory` and `--max_time`.

## Containers

| Image | Contents |
|---|---|
| `align` | dorado 1.2.0, samtools 1.21 |
| `hts` | samtools 1.21, bedtools 2.31.1, modkit 0.5.0 |
| `crossnn` | crossNN @26e4db9 (code only), torch 2.10 CPU, scikit-learn 1.6.1 |
| `methylyzr` | MethyLYZR @f78855e, unmodified |
| `sturgeon` | Sturgeon @d86d20f |
| `lamprey` | Lamprey @e885837, modkit 0.5.0 |
| `report` | matplotlib, pandas, pyyaml (PDF report + CNV segment plot) |
| `areebapatel/rapid_cns` | cnvpytor, pinned by digest |

Package versions match the environments the GUI runs in. The models are inputs,
not baked into the images.

`hts`, `align` and `report` are public at `ghcr.io/rsankowski` (`--container_registry`).
The four classifier images (`crossnn`, `methylyzr`, `sturgeon`, `lamprey`) are
**not** published: `containers/build.sh` builds them locally as
`methylclass/<name>:1.0.0` (`--restricted_registry`) and never pushes them. The
Dockerfiles fetch each tool from its original repository, so each user obtains it
directly and accepts its licence.

## Files

```
main.nf                 workflow: discovery, alignment fan-out, per-tool branches, report join
nextflow.config         all parameters + profiles
conf/                   base (resources), modules (args + publish layout), containers, host, test
modules/                prepare · classifiers · cnv · nested · report
bin/                    crossnn_predict.py · make_report.py · cnv_segment_plot.py (on PATH in every task)
assets/nf/              crossNN hg19 probe BED, Lamprey class names
containers/             Dockerfiles + build.sh
scripts/download_assets.sh
tests/data/             dummy inputs for -profile test
```

## Credits

fr-methylclass only orchestrates other people's tools. Please cite the original publications:

- **crossNN**: https://gitlab.com/euskirchen-lab/crossnn
- **MethyLYZR**: https://github.com/marasteiger/MethyLYZR
- **Sturgeon**: https://github.com/marcpaga/sturgeon
- **Lamprey**: https://github.com/princessmaximacenter/Lamprey (model: https://huggingface.co/tachterberg/Lamprey)
- **Rapid-CNS2**: https://github.com/areebapatel/Rapid-CNS2_nf
- **cnvpytor**, **modkit**, **dorado**, **samtools**, **bedtools**, EPI2ME **wf-metagenomics**

## Licences

The pipeline code in this repository is under the Apache 2.0 licence (`LICENSE`).
It does **not** include any code or models of the classifiers, which come with their
own, much more restrictive terms. By building the images and downloading the models
you obtain them from their authors and must accept their licences yourself:

| Tool | Terms (summary, read the original) |
|---|---|
| crossNN | no licence published, so all rights reserved by the authors |
| MethyLYZR | MPG research licence: academic / not-for-profit research only; no commercial or clinical use, no alterations, no redistribution |
| Sturgeon | Oncode / Cyclomics evaluation licence: internal non-commercial research only; no clinical or diagnostic use, no redistribution, no derivative works; publishing results needs permission from Oncode and Cyclomics |
| Lamprey | Oncode / Cyclomics evaluation licence: internal non-commercial research only; no clinical use, no redistribution, no derivative works; inform Oncode and Cyclomics in writing before submitting results for publication |

None of these tools may be used for diagnosis or patient care under these terms.
