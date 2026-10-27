/*
 * Standalone copy-number profile: the cnvpytor step of rapidCNS2 without the
 * full pipeline, plus a genome-wide called-segment plot.
 */

process CNVPYTOR {
    tag "${meta.id}"
    label 'cnvpytor'

    input:
    tuple val(meta), val(genome), path(bam), path(bai), path(fasta), path(fai)

    output:
    tuple val(meta), path("${meta.id}.cnvpytor.calls.100000.tsv"), emit: calls
    tuple val(meta), path("${meta.id}_cnvpytor_100k.png"), emit: manhattan, optional: true
    path "${meta.id}_CNV.pytor", emit: pytor

    script:
    // only the 100 kb bin size: enough for the genome-wide profile, far faster
    // than also doing 1 kb / 10 kb
    def chroms = ((1..22).collect { "chr${it}" } + ['chrX', 'chrY']).join(' ')
    def root = "${meta.id}_CNV.pytor"
    """
    cnvpytor -root ${root} -rd ${bam} -j ${task.cpus}
    cnvpytor -root ${root} -his 100000 -j ${task.cpus}
    cnvpytor -root ${root} -partition 100000 -j ${task.cpus}
    cnvpytor -root ${root} -call 100000 -j ${task.cpus} > ${meta.id}.cnvpytor.calls.100000.tsv
    cnvpytor -root ${root} -plot manhattan 100000 -chrom ${chroms} -o ${meta.id}_cnvpytor_100k.png || true
    mv -f ${meta.id}_cnvpytor_100k.global.0000.png ${meta.id}_cnvpytor_100k.png 2>/dev/null || true
    """

    stub:
    """
    touch ${meta.id}.cnvpytor.calls.100000.tsv ${meta.id}_cnvpytor_100k.png ${meta.id}_CNV.pytor
    """
}

/*
 * cnvpytor's manhattan plot is a mean-normalised read-depth scatter that looks
 * alike for every sample; this draws the actual called gains/losses.
 */
process CNV_SEGMENT_PLOT {
    tag "${meta.id}"
    label 'report'

    input:
    tuple val(meta), path(calls), path(fai)

    output:
    tuple val(meta), path("${meta.id}.cnv_segments.png"), emit: png

    script:
    """
    cnv_segment_plot.py ${calls} ${meta.id} ${meta.id}.cnv_segments.png ${fai}
    """

    stub:
    """
    touch ${meta.id}.cnv_segments.png
    """
}
