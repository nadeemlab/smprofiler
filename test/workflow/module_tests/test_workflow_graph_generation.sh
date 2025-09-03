test_dir=nf_workflow_graph_generation
mkdir -p $test_dir
cp module_tests/.workflow.config $test_dir
cp .smprofiler_db.config.container $test_dir
cp module_tests/.graph.config $test_dir
cd $test_dir

smprofiler workflow configure --workflow='graph generation' --config-file=.workflow.config
nextflow run . || { echo "Error: Nextflow run failed"; exit 1; }

[ -e "results/feature_names.txt" ] || { echo "Error: results/feature_names.txt does not exist"; exit 1; }
cat "results/feature_names.txt"

set -e
python3.13 -c '
from smprofiler.graphs.util import load_hs_graphs
graphs, _ = load_hs_graphs("results/")
assert len(graphs) == 4, f"Error: Graph count ({len(graphs)}) does not match true value (4)."
'

function clean() {
    cd .. ;
    rm -rf $test_dir;
}

clean
