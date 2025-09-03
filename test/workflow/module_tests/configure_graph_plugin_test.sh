cd workflow
umask 000
smprofiler workflow configure --workflow='graph plugin' --config-file=module_tests/.cggnn.workflow.config
echo -e "\ndocker.runOptions = '--network workflow_isolated_temporary_test'\n" >> nextflow.config
