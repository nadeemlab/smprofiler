
nextflow.enable.dsl = 2

process echo_environment_variables {
    output:
    path 'workflow',                        emit: workflow
    path 'file_manifest_filename',          emit: file_manifest_filename
    path 'input_path',                      emit: input_path
    path 'study_file',                      emit: study_file
    path 'diagnosis_file',                  emit: diagnosis_file
    path 'interventions_file',              emit: interventions_file
    path 'samples_file',                    emit: samples_file
    path 'db_config_file',                  emit: db_config_file
    path 'subjects_file',                   emit: subjects_file
    path 'channels_file',                   emit: channels_file
    path 'phenotypes_file',                 emit: phenotypes_file

    script:
    """
    #!/bin/bash
    echo -n "${workflow_}" > workflow
    echo -n "${file_manifest_filename_}" > file_manifest_filename
    echo -n "${input_path_}" > input_path
    echo -n "${study_file_}" > study_file
    echo -n "${diagnosis_file_}" > diagnosis_file
    echo -n "${interventions_file_}" > interventions_file
    echo -n "${samples_file_}" > samples_file
    echo -n "${db_config_file_}" > db_config_file
    echo -n "${subjects_file_}" > subjects_file
    echo -n "${channels_file_}" > channels_file
    echo -n "${phenotypes_file_}" > phenotypes_file
    """
}

process generate_run_information {
    input:
    val workflow
    path file_manifest_file
    val input_path
    path samples_file

    output:
    path 'job_specification_table.csv',     emit: job_specification_table

    script:
    """
    smprofiler workflow generate-run-information \
     --use-file-based-data-model \
     --workflow='${workflow}' \
     --file-manifest-file=${file_manifest_file} \
     --input-path='${input_path}' \
     --samples-file=${samples_file} \
     --job-specification-table=job_specification_table.csv
    """
}

process workflow_main {
    input:
    val workflow
    path file_manifest_file
    path channels_file
    path phenotypes_file
    path samples_file
    path db_config_file
    path subjects_file
    path cell_manifest_files
    path study
    path diagnosis
    path interventions

    script:
    """
    smprofiler workflow initialize \
     --workflow='${workflow}' \
     --file-manifest-file=${file_manifest_file} \
     --samples-file=${samples_file} \
     --database-config-file=${db_config_file} \
     --subjects-file=${subjects_file} \
     --study-file=${study} \
     --diagnosis-file=${diagnosis} \
     --interventions-file=${interventions} \
     --channels-file=${channels_file} \
     --phenotypes-file=${phenotypes_file} ;
    smprofiler ondemand assess-recreate-cache \
     --database-config-file=${db_config_file} \
     --study-file=${study} ;
    """
}

process report_run_configuration {
    publishDir 'results'

    input:
    path all_cell_manifests
    val workflow
    path file_manifest_file
    path samples_file
    path channels
    path phenotypes

    output:
    path "run_configuration.log"

    script:
    """
    smprofiler workflow report-run-configuration \
     --workflow='${workflow}' \
     --file-manifest-file=${file_manifest_file} \
     --samples-file=${samples_file} \
     --channels-file=${channels} \
     --phenotypes-file=${phenotypes} | tee run_configuration.log
    """
}

workflow {
    echo_environment_variables()
        .set{ environment_ch }

    environment_ch.file_manifest_filename.map{ file(it.text) }
        .set{ file_manifest_ch }

    environment_ch.workflow.map{ it.text }
        .set{ workflow_ch }

    environment_ch.input_path.map{ it.text }
        .set{ input_path_ch }

    environment_ch.study_file.map{ file(it.text) }
        .set{ study_ch }

    environment_ch.diagnosis_file.map{ file(it.text) }
        .set{ diagnosis_ch }

    environment_ch.interventions_file.map{ file(it.text) }
        .set{ interventions_ch }

    environment_ch.channels_file.map{ file(it.text) }
        .set{ channels_ch }

    environment_ch.phenotypes_file.map{ file(it.text) }
        .set{ phenotypes_ch }

    environment_ch.db_config_file.map{ file(it.text) }
        .set{ db_config_file_ch }

    environment_ch.subjects_file.map{ file(it.text) }
        .set{ subjects_file_ch }

    environment_ch.samples_file.map{ file(it.text) }
        .set{ samples_file_ch }

    generate_run_information(
        workflow_ch,
        file_manifest_ch,
        input_path_ch,
        samples_file_ch,
    ).set { run_information_ch }

    run_information_ch
        .job_specification_table
        .splitCsv(header: true)
        .map{ row -> tuple(row.input_file_identifier, file(row.input_filename)) }
        .set{ job_specifications_ch }

    job_specifications_ch
        .map{ row -> row[1] }
        .collect()
        .set{ cell_manifest_files_ch }

    report_run_configuration(
        cell_manifest_files_ch,
        workflow_ch,
        file_manifest_ch,
        samples_file_ch,
        channels_ch,
        phenotypes_ch,
    )

    workflow_main(
        workflow_ch,
        file_manifest_ch,
        channels_ch,
        phenotypes_ch,
        samples_file_ch,
        db_config_file_ch,
        subjects_file_ch,
        cell_manifest_files_ch,
        study_ch,
        diagnosis_ch,
        interventions_ch,
    )
}
