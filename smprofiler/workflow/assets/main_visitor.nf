
nextflow.enable.dsl = 2

process echo_environment_variables {
    output:
    path 'workflow',                        emit: workflow
    path 'db_config_file',                  emit: db_config_file
    path 'study_name',                      emit: study_name

    script:
    """
    #!/bin/bash
    echo -n "${workflow_}" > workflow
    echo -n "${db_config_file_}" > db_config_file
    echo -n "${study_name_}" > study_name
    """
}

process generate_run_information {
    input:
    val workflow
    val study_name
    val db_config_file

    output:
    path 'job_specification_table.csv',     emit: job_specification_table

    script:
    """
    smprofiler workflow generate-run-information \
     --workflow="${workflow}" \
     --study-name="${study_name}" \
     --database-config-file="${db_config_file}" \
     --job-specification-table=job_specification_table.csv ;
    """
}

process workflow_initialize {
    input:
    val workflow
    val study_name
    path db_config_file

    output:
    stdout                                  emit: initialization_flag

    script:
    """
    smprofiler workflow initialize \
     --workflow="${workflow}" \
     --study-name="${study_name}" \
     --database-config-file=${db_config_file}
    echo "Success"
    """
}

process core_job {
    memory { 2.GB * task.attempt }

    errorStrategy { task.exitStatus in 137..140 ? 'retry' : 'terminate' }
    maxRetries 4

    input:
    val initialization_flag
    val workflow
    val study_name
    val job_index
    path db_config_file

    output:
    path "performance_report${job_index}.csv",         emit: performance_report
    path "core_computation_results${job_index}.file",  emit: core_computation_results

    script:
    """
    smprofiler workflow core-job \
     --workflow="${workflow}" \
     --study-name="${study_name}" \
     --job-index="${job_index}" \
     --performance-report-file=performance_report${job_index}.csv \
     --database-config-file=${db_config_file} \
     --results-file=core_computation_results${job_index}.file
    """
}

process merge_performance_reports {
    publishDir 'results'

    input:
    path all_performance_reports

    output:
    path 'performance_report.md'

    script:
    """
    smprofiler workflow merge-performance-reports ${all_performance_reports} --output=performance_report.md
    """
}

process aggregate_results {
    memory { 2.GB * task.attempt }

    errorStrategy { task.exitStatus in 137..140 ? 'retry' : 'terminate' }
    maxRetries 6

    publishDir 'results'

    input:
    path db_config_file
    val workflow
    val study_name
    path 'performance_report.md'
    path all_core_computation_results

    script:
    """
    smprofiler workflow aggregate-core-results \
     ${all_core_computation_results} \
     --workflow="${workflow}" \
     --study-name="${study_name}" \
     --database-config-file=${db_config_file}
    """
}

workflow {
    echo_environment_variables()
        .set{ environment_ch }

    environment_ch.study_name.map{ it.text }
        .set{ study_name_ch }

    environment_ch.workflow.map{ it.text }
        .set{ workflow_ch }

    environment_ch.db_config_file.map{ file(it.text) }
        .set{ db_config_file_ch }

    generate_run_information(
        workflow_ch,
        study_name_ch,
        db_config_file_ch,
    ).set { run_information_ch }

    run_information_ch
        .job_specification_table
        .splitCsv(header: true)
        .map{ row -> tuple(row.job_index, row.sample_identifier) }
        .set{ job_specifications_ch }

    workflow_initialize(
        workflow_ch,
        study_name_ch,
        db_config_file_ch,
    )
        .initialization_flag
        .set{ initialization_flag_ch }


    job_specifications_ch
        .map{ row -> row[0] }
        .set{job_indices_ch}

    core_job(
        initialization_flag_ch,
        workflow_ch,
        study_name_ch,
        job_indices_ch,
        db_config_file_ch,
    )
        .set { core_job_results_ch }

    merge_performance_reports(
        core_job_results_ch.performance_report.collect()
    )
        .set{final_performance_report_ch}

    aggregate_results(
        db_config_file_ch,
        workflow_ch,
        study_name_ch,
        final_performance_report_ch,
        core_job_results_ch.core_computation_results.collect(),
    )
}
