/*
 * One-page PDF report per sample from whatever tools ran. Missing pieces are
 * annotated as "no data" in the PDF rather than failing the report.
 */

// "--flag file" for an input that was staged, nothing for a missing one
def optArg(String flag, f) {
    f ? "${flag} ${f}" : ''
}

process REPORT {
    tag "${meta.id}"
    label 'report'

    input:
    tuple val(meta), path(crossnn_top), path(methylyzr_csv), path(sturgeon_csv),
          path(lamprey_files), path(cnv_png), path(cnv_manhattan),
          val(raw_reads), val(aligned_reads)
    val with_lamprey

    output:
    tuple val(meta), path("${meta.id}_report.pdf"), emit: pdf

    script:
    def lfiles = lamprey_files instanceof List ? lamprey_files : [lamprey_files]
    def lamprey_csv = lfiles.find { it && it.name.endsWith('.csv') }
    def lamprey_classes = lfiles.find { it && it.name.endsWith('.yaml') && it.size() > 0 }
    def lamprey = with_lamprey
        ? "--lamprey ${lamprey_csv ?: 'missing_lamprey.csv'} ${optArg('--lamprey-classes', lamprey_classes)}" : ''
    def pid = params.patient_id ? "--patient-id '${params.patient_id}'" : ''
    """
    make_report.py --sample ${meta.id} --out ${meta.id}_report.pdf \\
        ${optArg('--crossnn', crossnn_top)} ${optArg('--methylyzr', methylyzr_csv)} \\
        ${optArg('--sturgeon', sturgeon_csv)} ${optArg('--cnv', cnv_png)} \\
        ${optArg('--cnv-manhattan', cnv_manhattan)} ${lamprey} \\
        --raw-reads '${raw_reads ?: ''}' --aligned-reads '${aligned_reads ?: ''}' ${pid}
    """

    stub:
    """
    touch ${meta.id}_report.pdf
    """
}
