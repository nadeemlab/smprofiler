query="http://smprofiler-apiserver-testing-apiserver:8080/channels/?study=Melanoma%20intralesional%20IL2"

curl -s $query | python -m json.tool | tee summary_rc.json | tr '\n' ' ' | sed 's/ \+//g'
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

diff module_tests/expected_channels.json summary_rc.json
status=$?
[ $status -eq 0 ] || (echo "API query for phenotype summary failed."; )

if [ $status -eq 0 ];
then
        rm summary_rc.json
    exit 0
else
        cat summary_rc.json
        rm summary_rc.json
    exit 1
fi
