nextflow.enable.dsl = 2

process prep_graph_creation {
    input:
    path db_config_file
    path graph_config_file

    output:
    path 'parameters.pkl',                      emit: parameter_file
    path 'specimens/*',                         emit: specimen_files


    script:
    """
    #!/bin/bash
    cp ${db_config_file} smprofiler_db.config
    smprofiler graphs prepare-graph-creation \
        --config_path ${graph_config_file} \
        --output_directory .
    """
}

process create_specimen_graphs {
    input:
    path parameters_file
    path specimen_file

    output:
    path "${specimen_file.baseName}.pkl",   optional: true, emit: specimen_graph

    script:
    """
    #!/bin/bash

    smprofiler graphs create-specimen-graphs \
        --specimen_hdf_path ${specimen_file} \
        --parameters_path ${parameters_file} \
        --output_directory .
    """
}

process finalize_graphs {
    publishDir '.', mode: 'copy'

    input:
    path parameters_file
    path graph_files

    output:
    path "results/",                     emit: working_directory

    script:
    """
    #!/bin/bash

    graph_files_array=(${graph_files})

    smprofiler graphs finalize-graphs \
        --graph_files "\${graph_files_array[@]}" \
        --parameters_path ${parameters_file} \
        --output_directory results
    """
}

workflow generate_graphs {
    take:
        db_config_file_ch
        graph_config_file_ch

    main:
        prep_graph_creation(
            db_config_file_ch,
            graph_config_file_ch,
        ).set{ prep_out }

        prep_out.parameter_file
            .set{ parameters_ch }

        prep_out.specimen_files
            .flatten()
            .set{ specimens_ch }

        create_specimen_graphs(
            parameters_ch,
            specimens_ch
        ).set{ specimen_graphs_ch }

        specimen_graphs_ch
            .filter { it != null }
            .collect()
            .set{ all_specimen_graphs_ch }

        finalize_graphs(
            parameters_ch,
            all_specimen_graphs_ch
        ).set{ finalize_out }

        finalize_out.working_directory
            .set{ working_directory_ch }

    emit:
        working_directory_ch
}
