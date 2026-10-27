/*
 * Methylation classifiers: crossNN, MethyLYZR, Sturgeon, Lamprey.
 * Commands mirror pipelines.py of the GUI (and the production notebooks).
 */

/*
 * CpG pileup, strands combined. Extra flags come from ext.args — crossNN adds
 * --combine-mods (sums 5mC+5hmC so the hemi-methyl signal is kept); Sturgeon
 * keeps the 5mC 'm' code it needs, so it runs without.
 */
process MODKIT_PILEUP {
    tag "${meta.id}"
    label 'hts'

    input:
    tuple val(meta), val(genome), path(bam), path(bai), path(fasta), path(fai)

    output:
    tuple val(meta), path("${meta.id}.5mC.bedmethyl"), emit: bedmethyl

    script:
    def args = task.ext.args ?: ''
    """
    modkit pileup ${bam} ${meta.id}.5mC.bedmethyl \\
        --ref ${fasta} --cpg --combine-strands ${args} --threads ${task.cpus}
    """

    stub:
    """
    touch ${meta.id}.5mC.bedmethyl
    """
}

process CROSSNN_ANNOTATE {
    tag "${meta.id}"
    label 'hts'

    input:
    tuple val(meta), path(bedmethyl)
    path probes_bed

    output:
    tuple val(meta), path("${meta.id}.annotated.bedmethyl"), emit: annotated

    script:
    """
    set -o pipefail
    bedtools intersect -a ${bedmethyl} -b ${probes_bed} -wa -wb \\
        | awk 'BEGIN{OFS="\\t"} {print \$1,\$2,\$3,\$22,\$5,\$6,\$7,\$8,\$9,\$10,\$11}' \\
        > ${meta.id}.annotated.bedmethyl
    if [ ! -s ${meta.id}.annotated.bedmethyl ]; then
        echo "crossNN: no CpGs overlap the probe BED" >&2
        exit 1
    fi
    """

    stub:
    """
    touch ${meta.id}.annotated.bedmethyl
    """
}

process CROSSNN_PREDICT {
    tag "${meta.id}"
    label 'crossnn'

    input:
    tuple val(meta), path(annotated)
    tuple path(capper_model), path(pancan_model)

    output:
    tuple val(meta), path("${meta.id}_crossnn_top.tsv"), emit: top
    tuple val(meta), path("${meta.id}_crossnn_all_scores.tsv"), emit: all

    script:
    // model keys are what make_report.py looks up
    """
    crossnn_predict.py ${params.crossnn_repo} ${annotated} ${meta.id} \\
        ${meta.id}_crossnn ${params.crossnn_top_n} \\
        brain_tumor_Capper=${capper_model} pan_cancer=${pancan_model}
    """

    stub:
    """
    printf 'sample\\tmodel\\trank\\tclass\\tscore\\tn_features\\n' > ${meta.id}_crossnn_top.tsv
    cp ${meta.id}_crossnn_top.tsv ${meta.id}_crossnn_all_scores.tsv
    """
}

/*
 * bam2feather processes one BAM per io-thread, so a single merged ONT BAM funnels
 * through ONE reader and takes hours. The sorted BAM is sharded by chromosome
 * (EPIC CpGs are on chr1-22/X/Y only, so no usable read is dropped) and the
 * shards are read in parallel.
 */
process METHYLYZR_FEATHER {
    tag "${meta.id}"
    label 'methylyzr'

    input:
    tuple val(meta), val(genome), path(bam), path(bai), path(fasta), path(fai)
    path epic_bed

    output:
    tuple val(meta), path("feather/${meta.id}.feather"), emit: feather

    script:
    def sort_t = Math.max(1, Math.min(task.cpus, params.sort_threads as int))
    """
    mkdir -p shards feather
    chroms=\$(samtools view -H ${bam} | awk -F'\\t' '/^@SQ/{for(i=2;i<=NF;i++) if(\$i~/^SN:/) print substr(\$i,4)}' \\
        | grep -xE 'chr([0-9]|1[0-9]|2[0-2]|X|Y)' || true)
    n=0
    for c in \$chroms; do
        samtools view -b -@ ${sort_t} ${bam} \$c -o shards/${meta.id}.\$c.bam
        n=\$((n + 1))
    done
    echo "Sharded ${meta.id} into \$n chromosome shards for parallel bam2feather"
    io_t=\$(( n < 12 ? n : 12 )); [ \$io_t -ge 1 ] || io_t=1

    python3 ${params.methylyzr_dir}/scripts/bam2feather.py -i shards -s ${meta.id} \\
        --sites ${epic_bed} -o feather \\
        --methylation_threads ${task.cpus} --io_threads \$io_t
    rm -rf shards
    if [ ! -f feather/${meta.id}.feather ]; then
        echo "bam2feather produced no feather for ${meta.id} ('No data retrieved')." >&2
        echo "No reads overlapped the EPIC CpG sites - check the reads aligned to hg38 (mapq>=10) and carry MM/ML tags." >&2
        exit 1
    fi
    """

    stub:
    """
    mkdir -p feather && touch feather/${meta.id}.feather
    """
}

process METHYLYZR_CLASSIFY {
    tag "${meta.id}"
    label 'methylyzr'

    input:
    tuple val(meta), path(feather)
    tuple path(betas), path(weights), path(priors)

    output:
    tuple val(meta), path("results/MethyLYZR_${meta.id}.csv"), emit: csv
    path "results/*", emit: all

    script:
    // MPLBACKEND=Agg: MethyLYZR.py ends with a blocking plt.show()
    """
    mkdir -p results
    MPLBACKEND=Agg python3 ${params.methylyzr_dir}/MethyLYZR.py -i ${feather} -s ${meta.id} \\
        -o results -c ${betas} -w ${weights} -p ${priors}
    """

    stub:
    """
    mkdir -p results
    printf 'Class,Posterior Probability\\n' > results/MethyLYZR_${meta.id}.csv
    """
}

process STURGEON {
    tag "${meta.id}"
    label 'sturgeon'

    input:
    tuple val(meta), path(bedmethyl)
    path model

    output:
    tuple val(meta), path("${meta.id}/${meta.id}_sturgeon_general.csv"), emit: csv
    path "${meta.id}/*", emit: all

    script:
    // inputtobed os.removedirs() its output path and every empty parent, so it
    // writes into the task root and the bed is moved into the results dir after
    """
    sturgeon inputtobed -i ${bedmethyl} -o ${meta.id}_sturgeon.bed \\
        -s modkit_pileup --reference-genome ${params.sturgeon_reference_genome}
    rm -f ${meta.id}_sturgeon.bed.tmp
    mkdir -p ${meta.id}
    mv ${meta.id}_sturgeon.bed ${meta.id}/
    sturgeon predict -i ${meta.id}/${meta.id}_sturgeon.bed -o ${meta.id} \\
        -m ${model} --plot-results
    """

    stub:
    """
    mkdir -p ${meta.id}
    printf 'number_probes\\n0\\n' > ${meta.id}/${meta.id}_sturgeon_general.csv
    """
}

/*
 * Lamprey: haematological-malignancy classifier (86 types, no CNS tumour classes).
 * lamprey-preprocess runs modkit pileup over its bundled hg38 probe manifest and
 * binarises the calls.
 */
process LAMPREY_PREPROCESS {
    tag "${meta.id}"
    label 'lamprey'

    input:
    tuple val(meta), val(genome), path(bam), path(bai), path(fasta), path(fai)

    output:
    tuple val(meta), path("${meta.id}_lamprey_probes.tsv"), emit: probes
    path "${meta.id}.lamprey_pileup.bed", emit: pileup, optional: true

    script:
    """
    lamprey-preprocess -i ${bam} -o ${meta.id}_lamprey_probes.tsv \\
        --genome ${params.lamprey_genome} --ref ${fasta} -t ${task.cpus} \\
        --modkit \$(command -v modkit) --pileup-out ${meta.id}.lamprey_pileup.bed
    """

    stub:
    """
    touch ${meta.id}_lamprey_probes.tsv
    """
}

process LAMPREY_PREDICT {
    tag "${meta.id}"
    label 'lamprey'

    input:
    tuple val(meta), path(probes)
    path model_dir, stageAs: 'lamprey_model'
    val model_ref

    output:
    tuple val(meta), path("${meta.id}_lamprey.csv"), path("${meta.id}_lamprey_report.txt"),
          path("lamprey_classes.yaml"), emit: result
    path "${meta.id}_lamprey*", emit: all

    script:
    // a local model dir is staged and model_ref is the path inside it (a HF
    // cache snapshot is staged from its repo dir so its blob symlinks resolve);
    // otherwise model_ref is a HuggingFace repo id downloaded at run time
    def model = model_dir ? "lamprey_model/${model_ref}" : model_ref
    def offline = model_dir ? 'export HF_HUB_OFFLINE=1' : ''
    """
    export MPLBACKEND=Agg MPLCONFIGDIR=\$PWD/.mpl
    export HF_HOME=\${HF_HOME:-\$PWD/.hf_cache}
    ${offline}
    lamprey -i ${probes} -m ${model} -o ${meta.id}_lamprey.csv \\
        -d nanopore --plot --top-n ${params.lamprey_top_n}
    # class display names for the report, from the installed Lamprey package
    "\$(head -1 "\$(command -v lamprey)" | sed 's/^#!//')" -c \
        "import importlib.resources as r, shutil; shutil.copy(r.files('lamprey') / 'files/classification_system.yaml', 'lamprey_classes.yaml')" \
        || touch lamprey_classes.yaml
    """

    stub:
    """
    touch ${meta.id}_lamprey.csv ${meta.id}_lamprey_report.txt lamprey_classes.yaml
    """
}
