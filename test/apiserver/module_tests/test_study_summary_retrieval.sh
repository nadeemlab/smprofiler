
query=http://smprofiler-apiserver-testing-apiserver:8080/study-summary/?study=Melanoma%20intralesional%20IL2

echo "Querying first time."
curl -s $query ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

echo "Querying second time."
curl -s $query | python -m json.tool > summary.json

diff module_tests/expected_study_summary_structured.json summary.json
status=$?
[ $status -eq 0 ] || (echo "API query for study summary failed."; )

if [ $status -eq 0 ];
then
	rm summary.json
    exit 0
else
	cat summary.json
	rm summary.json
    exit 1
fi
