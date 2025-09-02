nextflow.enable.dsl = 2

include { generate_graphs } from './nf_files/graph_generation'

process echo_environment_variables {
    output:
    path 'db_config_file',                  emit: db_config_file
    path 'graph_config_file',               emit: graph_config_file

    script:
    """
    #!/bin/bash
    echo -n "${db_config_file_}" > db_config_file
    echo -n "${graph_config_file_}" > graph_config_file
    """
}

workflow {
    echo_environment_variables()
        .set{ environment_ch }
    
    environment_ch.db_config_file.map{ file(it.text) }
        .set{ db_config_file_ch }
    
    environment_ch.graph_config_file.map{ file(it.text) }
        .set{ graph_config_file_ch }
    
    generate_graphs(
        db_config_file_ch,
        graph_config_file_ch
    ).set{ working_directory_ch }
}
