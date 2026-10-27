/*
 * Third-party Nextflow pipelines launched as a single task (rapidCNS2 and EPI2ME
 * wf-metagenomics). These run on the host — they need `nextflow` plus their own
 * container engine — so they carry no container of their own.
 *
 * Each sample gets a persistent launch + work dir under params.nested_workdir, so
 * a re-run after a failure `-resume`s that sample's own session and reuses its
 * finished tasks instead of redoing hours of work.
 */

process RAPIDCNS2 {
    tag "${meta.id}"
    label 'nested'

    input:
    tuple val(meta), val(genome), path(bam), path(bai), path(fasta), path(fai)

    output:
    tuple val(meta), path("results-${meta.id}"), emit: results
    tuple val(meta), path("results-${meta.id}/cnv/${meta.id}.cnvpytor.calls.100000.tsv"), emit: calls, optional: true

    script:
    def launch = "${params.nested_workdir}/rapidcns2/${meta.id}"
    def rev = params.rapidcns2_revision ? "-r ${params.rapidcns2_revision}" : ''
    def cfg = params.rapidcns2_config ? "-c ${file(params.rapidcns2_config)}" : ''
    def extra = params.rapidcns2_extra_args ?: ''
    """
    out=\$PWD/results-${meta.id}
    bam=\$(readlink -f ${bam}); ref=\$(readlink -f ${fasta})
    mkdir -p "\$out" ${launch}
    cd ${launch}
    NXF_VER=${params.rapidcns2_nxf_ver} ${params.nextflow_bin} run ${params.rapidcns2_pipeline} ${rev} \\
        --input "\$bam" --id ${meta.id} --outDir "\$out" --logDir "\$out" \\
        -w ${launch}/work --ref "\$ref" \\
        --annovarPath ${params.annovar_path} --annovarDB ${params.annovar_db} \\
        --annotsvAnnot ${params.annotsv_annot} --runHumanVariation true \\
        --annotations ${params.rapidcns2_annotations} --cnvGenes ${params.rapidcns2_cnv_genes} \\
        --panel ${params.rapidcns2_panel} --mnpFlex true --methThreads ${params.rapidcns2_meth_threads} \\
        -profile ${params.rapidcns2_profile} ${cfg} ${extra} -resume
    """

    stub:
    """
    mkdir -p results-${meta.id}/cnv
    touch results-${meta.id}/cnv/${meta.id}.cnvpytor.calls.100000.tsv
    """
}

/*
 * Taxonomic classification of the raw reads (no human alignment); the workflow
 * takes uBAM directly. Needs internet on first run for the pull + database.
 */
process METAGENOMICS {
    tag "${meta.id}"
    label 'nested'

    input:
    tuple val(meta), path(reads)

    output:
    tuple val(meta), path("results-${meta.id}"), emit: results

    script:
    def launch = "${params.nested_workdir}/metagenomics/${meta.id}"
    def rev = params.metagenomics_revision ? "-r ${params.metagenomics_revision}" : ''
    def extra = params.metagenomics_extra_args ?: ''
    """
    out=\$PWD/results-${meta.id}
    reads=\$(readlink -f ${reads})
    mkdir -p "\$out" ${launch}
    cd ${launch}
    ${params.nextflow_bin} run ${params.metagenomics_workflow} ${rev} \\
        --bam "\$reads" --sample ${meta.id} \\
        --classifier ${params.metagenomics_classifier} --database_set ${params.metagenomics_database_set} \\
        --out_dir "\$out" -w ${launch}/work -profile ${params.metagenomics_profile} ${extra} -resume
    """

    stub:
    """
    mkdir -p results-${meta.id}
    """
}
