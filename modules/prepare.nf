/*
 * Input preparation: reference index, fragment merge, alignment, read counts.
 */

process SAMTOOLS_FAIDX {
    tag "${genome}"
    label 'hts'

    input:
    tuple val(genome), path(fasta)

    output:
    tuple val(genome), path(fasta), path("${fasta}.fai")

    script:
    """
    samtools faidx ${fasta}
    """

    stub:
    """
    touch ${fasta}.fai
    """
}

/*
 * Coordinate-sorted, indexed BAM for one sample on one genome.
 *
 * Split ONT fragments are merged with `samtools cat` (they share a header), then
 * aligned with `dorado aligner`, which keeps the MM/ML modification tags. A
 * single input that is already aligned (header has @SQ) is only sorted+indexed.
 * Each (sample, genome) pair runs once and is shared by every tool on that genome.
 */
process ALIGN {
    tag "${meta.id}:${genome}"
    label 'align'

    input:
    tuple val(meta), path(bams, stageAs: 'input/*'), val(genome), path(fasta), path(fai)

    output:
    tuple val(meta), val(genome), path("${meta.id}.sorted.bam"), path("${meta.id}.sorted.bam.bai"), path(fasta), path(fai), emit: bam

    script:
    def n = bams instanceof List ? bams.size() : 1
    def sort_t = Math.max(1, Math.min(task.cpus, params.sort_threads as int))
    """
    set -o pipefail
    first=\$(ls input/*.bam | head -n1)
    if [ ${n} -eq 1 ] && samtools view -H "\$first" | grep -q '^@SQ'; then
        echo "Input already aligned - sorting/indexing only."
        samtools sort -@ ${sort_t} -m 1G -o ${meta.id}.sorted.bam "\$first"
    else
        if [ ${n} -gt 1 ]; then
            echo "Merging ${n} BAM fragment(s) -> ${meta.id}"
            samtools cat -o merged.bam input/*.bam
            src=merged.bam
        else
            src="\$first"
        fi
        echo "Aligning ${meta.id} to ${genome} (dorado aligner) ..."
        dorado aligner --no-sort -t ${task.cpus} ${fasta} "\$src" > aligned.bam
        samtools sort -@ ${sort_t} -m 1G -o ${meta.id}.sorted.bam aligned.bam
        rm -f merged.bam aligned.bam
    fi
    samtools index -@ ${sort_t} ${meta.id}.sorted.bam
    """

    stub:
    """
    touch ${meta.id}.sorted.bam ${meta.id}.sorted.bam.bai
    """
}

/*
 * Raw (unaligned) reads as one BAM in an isolated directory, for workflows that
 * classify raw reads (wf-metagenomics).
 */
process MERGE_RAW {
    tag "${meta.id}"
    label 'hts'

    input:
    tuple val(meta), path(bams, stageAs: 'input/*')

    output:
    tuple val(meta), path("reads"), emit: reads

    script:
    def n = bams instanceof List ? bams.size() : 1
    """
    mkdir -p reads
    if [ ${n} -gt 1 ]; then
        samtools cat -o reads/${meta.id}.bam input/*.bam
    else
        cp -L input/*.bam reads/${meta.id}.bam
    fi
    """

    stub:
    """
    mkdir -p reads && touch reads/${meta.id}.bam
    """
}

/*
 * Raw reads = records across the source BAM(s); aligned = primary mapped reads
 * in the preferred (hg38) aligned BAM. Shown in the PDF report header.
 */
process READ_COUNTS {
    tag "${meta.id}"
    label 'hts'

    input:
    tuple val(meta), path(bams, stageAs: 'input/*'), path(aligned_bam, stageAs: 'aligned/*')

    output:
    tuple val(meta), env('RAW'), env('ALIGNED'), emit: counts

    script:
    """
    RAW=0
    for b in input/*.bam; do
        RAW=\$(( RAW + \$(samtools view -c "\$b") ))
    done
    ALIGNED=""
    if ls aligned/*.bam >/dev/null 2>&1; then
        ALIGNED=\$(samtools view -c -F 0x904 aligned/*.bam)
    fi
    echo "reads - raw: \$RAW  aligned(primary): \${ALIGNED:-?}"
    """

    stub:
    """
    RAW=1000
    ALIGNED=900
    """
}
