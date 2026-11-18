#!/usr/bin/env nextflow
/*
 * Methylation classification of nanopore BAMs — Nextflow port of the
 * Methylation Classification GUI (pipelines.py).
 *
 * crossNN · MethyLYZR · Sturgeon V2 · Lamprey · standalone copy-number (cnvpytor)
 * · rapidCNS2 · EPI2ME wf-metagenomics · one-page PDF report per sample.
 *
 * EXPERIMENTAL — RESEARCH USE ONLY. Not validated for diagnostic use.
 */
nextflow.enable.dsl = 2

include { SAMTOOLS_FAIDX; ALIGN; MERGE_RAW; READ_COUNTS } from './modules/prepare'
include { MODKIT_PILEUP as CROSSNN_PILEUP;
          CROSSNN_ANNOTATE; CROSSNN_PREDICT; METHYLYZR_FEATHER; METHYLYZR_CLASSIFY;
          STURGEON_EXTRACT; STURGEON; LAMPREY_PREPROCESS; LAMPREY_PREDICT } from './modules/classifiers'
include { CNVPYTOR; CNV_SEGMENT_PLOT; CNV_SEGMENT_PLOT as RAPIDCNS2_SEGMENT_PLOT } from './modules/cnv'
include { RAPIDCNS2; METAGENOMICS } from './modules/nested'
include { REPORT } from './modules/report'

// "report" last: it gathers what the other tools wrote for the sample
def allTools() {
    ['crossnn', 'methylyzr', 'sturgeon', 'lamprey', 'rapidcns2', 'cnv', 'metagenomics', 'report']
}

/*
 * Group *.bam files into samples.
 *
 * --input takes a comma-separated list of BAM files and/or folders (searched
 * recursively), or a CSV samplesheet with columns `sample,bam` (several rows per
 * sample = fragments to merge).
 *
 * --group_by folder : BAMs sharing an immediate parent directory are one sample,
 *                     named after that directory (merges ONT bam_pass/<barcode>/
 *                     fragments). A BAM given as a direct path is its own sample.
 * --group_by file   : every BAM is its own sample, named by its stem.
 */
def discoverSamples(String input, String mode) {
    def groups = new TreeMap()

    input.tokenize(',').collect { it.trim() }.findAll { it }.each { raw ->
        def p = file(raw)
        if (!p.exists()) {
            log.warn "Input not found, skipped: ${raw}"
            return
        }
        if (p.isFile() && p.name.toLowerCase().endsWith('.csv')) {
            p.splitCsv(header: true).each { row ->
                if (!row.sample || !row.bam)
                    error "Samplesheet ${p} needs columns 'sample' and 'bam'"
                addBam(groups, row.sample.trim(), file(row.bam.trim(), checkIfExists: true))
            }
        } else if (p.isFile()) {
            if (p.name.toLowerCase().endsWith('.bam'))
                addBam(groups, p.name.replaceFirst(/(?i)\.bam$/, ''), p)
        } else {
            p.eachFileRecurse { f ->
                if (!f.isFile() || !f.name.toLowerCase().endsWith('.bam')) return
                def name = mode == 'file' ? f.name.replaceFirst(/(?i)\.bam$/, '') : f.parent.name
                addBam(groups, name, f)
            }
        }
    }
    groups.collect { name, bams -> [[id: name, n_bams: bams.size()], bams as List] }
}

def addBam(Map groups, String name, bam) {
    groups.computeIfAbsent(name) { new TreeSet() } << bam
}

// [meta, file] -> [sample id, file], for joining tool outputs per sample
def keyed(ch) {
    ch.map { meta, f -> [meta.id, f] }
}

// [meta, genome, bam, bai, fasta, fai] tuples aligned to one genome
def onGenome(ch_aln, String genome) {
    ch_aln.filter { it[1] == genome }
}

// Explicit param wins; else the file's place in --assets_dir (scripts/download_assets.sh layout)
def asset(value, String rel) {
    value ?: (params.assets_dir ? "${params.assets_dir}/${rel}" : null)
}

def requireFile(value, String what) {
    if (!value) error "Missing ${what}: set the parameter or --assets_dir"
    file(value, checkIfExists: true)
}

workflow {
    def ALL_TOOLS = allTools()
    def tools = params.tools == 'all' ? ALL_TOOLS
              : params.tools.tokenize(',').collect { it.trim().toLowerCase() }
    def unknown = tools - ALL_TOOLS
    if (unknown) error "Unknown tool(s): ${unknown.join(', ')}. Choose from: ${ALL_TOOLS.join(', ')}"
    if (!params.input) error "Missing --input (BAM files, folders or a sample,bam CSV)"
    if (!(params.group_by in ['folder', 'file'])) error "--group_by must be 'folder' or 'file'"

    def samples = discoverSamples(params.input as String, params.group_by as String)
    if (!samples) error "No *.bam files found under: ${params.input}"
    log.info "Methylation classification — EXPERIMENTAL, research use only"
    log.info "tools   : ${tools.join(', ')}"
    log.info "samples : ${samples.size()} from ${samples.sum { it[0].n_bams }} BAM(s)"
    samples.each { meta, bams -> log.info "  ${meta.id} <- ${bams.size()} BAM(s)" }

    // genome each tool aligns to; one alignment per (sample, genome) is shared
    def toolGenome = [crossnn  : params.crossnn_genome,  methylyzr: params.methylyzr_genome,
                      sturgeon : params.sturgeon_genome, lamprey  : params.lamprey_genome,
                      rapidcns2: params.rapidcns2_genome, cnv     : params.cnv_genome]
    def genomes = tools.findResults { toolGenome[it] }.unique()

    def ch_samples = Channel.fromList(samples)

    // ---- references + alignment ---------------------------------------------
    def ch_aln = Channel.empty()
    def ch_ref = Channel.empty()
    if (genomes) {
        def refs = genomes.collect { g ->
            def fa = params["${g}_fasta"]
            if (!fa) error "Tools ${tools.findAll { toolGenome[it] == g }} need --${g}_fasta"
            [g, file(fa, checkIfExists: true)]
        }
        def ch_fasta = Channel.fromList(refs)
            .branch { g, fa -> indexed: file("${fa}.fai").exists(); missing: true }
        SAMTOOLS_FAIDX(ch_fasta.missing)
        ch_ref = ch_fasta.indexed.map { g, fa -> [g, fa, file("${fa}.fai")] }
            .mix(SAMTOOLS_FAIDX.out)

        ALIGN(ch_samples.combine(ch_ref))
        ch_aln = ALIGN.out.bam
    }

    def ch_crossnn = Channel.empty()
    def ch_methylyzr = Channel.empty()
    def ch_sturgeon = Channel.empty()
    def ch_lamprey = Channel.empty()
    def ch_cnv_png = Channel.empty()
    def ch_cnv_manhattan = Channel.empty()

    // ---- crossNN ------------------------------------------------------------
    if ('crossnn' in tools) {
        def models = [requireFile(asset(params.crossnn_model_capper, 'crossnn/Capper_et_al_NN.pkl'), 'crossNN Capper model'),
                      requireFile(asset(params.crossnn_model_pancan, 'crossnn/pancan_devel_v5i_NN.pkl'), 'crossNN pan-cancer model')]
        CROSSNN_PILEUP(onGenome(ch_aln, toolGenome.crossnn))
        CROSSNN_ANNOTATE(CROSSNN_PILEUP.out.bedmethyl, requireFile(params.crossnn_probes, 'crossNN probe BED'))
        CROSSNN_PREDICT(CROSSNN_ANNOTATE.out.annotated, models)
        ch_crossnn = keyed(CROSSNN_PREDICT.out.top)
    }

    // ---- MethyLYZR ----------------------------------------------------------
    if ('methylyzr' in tools) {
        def model = [requireFile(asset(params.methylyzr_betas, 'methylyzr/betas_mean.feather'), 'MethyLYZR centroids'),
                     requireFile(asset(params.methylyzr_weights, 'methylyzr/W_RELIEF.feather'), 'MethyLYZR weights'),
                     requireFile(asset(params.methylyzr_priors, 'methylyzr/class_priors.csv'), 'MethyLYZR priors')]
        def epic = requireFile(asset(params.methylyzr_epic_bed, 'methylyzr/EPIC_CpGannotation.bed'), 'MethyLYZR EPIC BED')
        METHYLYZR_FEATHER(onGenome(ch_aln, toolGenome.methylyzr), epic)
        METHYLYZR_CLASSIFY(METHYLYZR_FEATHER.out.feather, model)
        ch_methylyzr = keyed(METHYLYZR_CLASSIFY.out.csv)
    }

    // ---- Sturgeon V2 (T2T-CHM13v2.0 only) ------------------------------------
    if ('sturgeon' in tools) {
        def model = requireFile(asset(params.sturgeon_model, 'sturgeon/cns-v2.5.zip'), 'Sturgeon V2 model')
        STURGEON_EXTRACT(onGenome(ch_aln, toolGenome.sturgeon), model)
        STURGEON(STURGEON_EXTRACT.out.calls, model)
        ch_sturgeon = keyed(STURGEON.out.scores)
    }

    // ---- Lamprey ------------------------------------------------------------
    if ('lamprey' in tools) {
        def lm = asset(params.lamprey_model, 'lamprey/model')
        // local snapshot dir -> staged; anything else is a HuggingFace repo id
        def local = lm && file(lm).exists()
        if (!local) log.warn "Lamprey model '${lm ?: 'tachterberg/Lamprey'}' is not a local path — it will be downloaded from HuggingFace in every task"
        if (!lm) lm = 'tachterberg/Lamprey'
        // a HuggingFace cache snapshot holds symlinks into ../../blobs: stage the
        // whole models--org--name dir so they resolve inside a container
        def model_dir = []
        def model_ref = lm
        if (local) {
            def m = (file(lm).toString() =~ /^(.*\/models--[^\/]+)\/(snapshots\/[^\/]+)$/)
            model_dir = m ? file(m[0][1]) : file(lm)
            model_ref = m ? m[0][2] : '.'
        }
        LAMPREY_PREPROCESS(onGenome(ch_aln, toolGenome.lamprey))
        LAMPREY_PREDICT(LAMPREY_PREPROCESS.out.probes, model_dir, model_ref)
        ch_lamprey = LAMPREY_PREDICT.out.result.map { meta, csv, txt, classes -> [meta.id, [csv, txt, classes]] }
    }

    // ---- standalone copy-number ---------------------------------------------
    if ('cnv' in tools) {
        CNVPYTOR(onGenome(ch_aln, toolGenome.cnv))
        def fai = ch_ref.filter { it[0] == params.cnv_genome }.map { it[2] }
        CNV_SEGMENT_PLOT(CNVPYTOR.out.calls.combine(fai))
        ch_cnv_png = keyed(CNV_SEGMENT_PLOT.out.png)
        ch_cnv_manhattan = keyed(CNVPYTOR.out.manhattan)
    }

    // ---- rapidCNS2 (nested Nextflow pipeline) -------------------------------
    if ('rapidcns2' in tools) {
        RAPIDCNS2(onGenome(ch_aln, toolGenome.rapidcns2))
        def fai = ch_ref.filter { it[0] == params.rapidcns2_genome }.map { it[2] }
        RAPIDCNS2_SEGMENT_PLOT(RAPIDCNS2.out.calls.combine(fai))
    }

    // ---- metagenomics (nested Nextflow pipeline, raw reads) -----------------
    if ('metagenomics' in tools) {
        MERGE_RAW(ch_samples)
        METAGENOMICS(MERGE_RAW.out.reads)
    }

    // ---- PDF report ---------------------------------------------------------
    if ('report' in tools) {
        // aligned-read count from the hg38 alignment when there is one
        def prefGenome = genomes.contains('hg38') ? 'hg38' : (genomes ? genomes[0] : null)
        def ch_pref = ch_aln.filter { it[1] == prefGenome }.map { [it[0].id, it[2]] }
        READ_COUNTS(
            ch_samples.map { meta, bams -> [meta.id, meta, bams] }
                .join(ch_pref, remainder: true)
                .map { id, meta, bams, bam -> [meta, bams, bam ?: []] })
        def ch_counts = READ_COUNTS.out.counts.map { meta, raw, aln -> [meta.id, [raw, aln]] }

        // left-join every tool's output on the sample; a tool that was not run
        // or failed for a sample leaves a gap, drawn as "no data" in the PDF
        def ch_rep = [ch_crossnn, ch_methylyzr, ch_sturgeon, ch_lamprey, ch_cnv_png, ch_cnv_manhattan, ch_counts]
            .inject(ch_samples.map { meta, bams -> [meta.id, meta] }) { acc, ch -> acc.join(ch, remainder: true) }
            .filter { it[1] != null }
            .map { id, meta, crossnn, mlyzr, sturgeon, lamprey, cnv, manhattan, counts ->
                [meta, crossnn ?: [], mlyzr ?: [], sturgeon ?: [], lamprey ?: [], cnv ?: [],
                 manhattan ?: [], counts ? counts[0] : '', counts ? counts[1] : '']
            }
        REPORT(ch_rep, tools.contains('lamprey'))
    }
}
