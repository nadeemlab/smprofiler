
query="http://smprofiler-apiserver-testing-apiserver:8080/phenotype-criteria/?study=Melanoma%20intralesional%20IL2&phenotype_symbol=Tumor"
echo ""
echo "Query: $query"

curl -s "$query" > /dev/null ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

curl -s $query | python -m json.tool > criteria.json

diff module_tests/expected_phenotype_criteria_structured.json criteria.json
status=$?
[ $status -eq 0 ] || (echo "API query for named phenotype criteria in the scope of a given study has failed."; )

if [ $status -eq 0 ];
then
	rm criteria.json
    exit 0
else
    echo "Response:"
	cat criteria.json
	rm criteria.json
    exit 1
fi
