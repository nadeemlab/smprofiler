nextflow.enable.dsl = 2

include { generate_graphs } from './nf_files/graph_generation'


process echo_environment_variables {
    output:
    path 'db_config_file',                          emit: db_config_file
    path 'graph_config_file',                       emit: graph_config_file
    path 'graph_plugin_image',                      emit: graph_plugin_image
    path 'graph_plugin_singularity_run_options',    emit: graph_plugin_singularity_run_options
    path 'upload_importances',                      emit: upload_importances

    script:
    """
    #!/bin/bash
    echo -n "${db_config_file_}" > db_config_file
    echo -n "${graph_config_file_}" > graph_config_file
    echo -n "${graph_plugin_image_}" > graph_plugin_image
    echo -n "${graph_plugin_singularity_run_options_}" > graph_plugin_singularity_run_options
    echo -n "${upload_importances_}" > upload_importances
    """
}

process train {
    publishDir '.', mode: 'copy'

    container "${graph_plugin_image}"
    containerOptions "${graph_plugin_singularity_run_options}"

    input:
    val graph_plugin_image
    val graph_plugin_singularity_run_options
    path working_directory
    path graph_config_file

    output:
    path "${working_directory}/importances.csv",     emit: importances_csv_path
    path "${working_directory}/",                    emit: working_directory

    script:
    """
    #!/bin/bash

    smprofiler-plugin-train-on-graphs \
        --input_directory ${working_directory} \
        --config_file ${graph_config_file} \
        --output_directory ${working_directory}
    """
}

process upload_importance_scores {
    input:
    val upload_importances
    path importances_csv_path
    path db_config_file
    path graph_config_file

    script:
    """
    #!/bin/bash

    if [[ "${upload_importances}" == "True" ]]
    then
        cp ${db_config_file} smprofiler_db.config
        smprofiler graphs upload-importances \
            --importances_csv_path ${importances_csv_path} \
            --config_path ${graph_config_file}
    fi
    """
}

workflow {
    echo_environment_variables()
        .set{ environment_ch }
    
    environment_ch.db_config_file.map{ file(it.text) }
        .set{ db_config_file_ch }
    
    environment_ch.graph_config_file.map{ file(it.text) }
        .set{ graph_config_file_ch }
    
    environment_ch.graph_plugin_image.map{ it.text }
        .set{ graph_plugin_image_ch }
    
    environment_ch.graph_plugin_singularity_run_options.map{ it.text }
        .set{ graph_plugin_singularity_run_options_ch }

    environment_ch.upload_importances.map{ it.text }
        .set{ upload_importances_ch }

    generate_graphs(
        db_config_file_ch,
        graph_config_file_ch,
    ).set{ working_directory_ch }

    train(
        graph_plugin_image_ch,
        graph_plugin_singularity_run_options_ch,
        working_directory_ch,
        graph_config_file_ch,
    ).set{ train_out }

    train_out.importances_csv_path
        .set{ importances_csv_path_ch }

    train_out.working_directory
        .set{ working_directory_ch }

    upload_importance_scores(
        upload_importances_ch,
        importances_csv_path_ch,
        db_config_file_ch,
        graph_config_file_ch,
    )
}
