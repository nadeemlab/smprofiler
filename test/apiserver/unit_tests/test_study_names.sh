
query=http://smprofiler-apiserver-testing-apiserver:8080/study-names/

curl -s $query ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

curl -s $query | python -m json.tool > names.json

diff unit_tests/expected_study_names.json names.json
status=$?
[ $status -eq 0 ] || (echo "API query for study name pairs failed."; )

if [ $status -eq 0 ];
then
	rm names.json
    exit 0
else
	cat names.json
	rm names.json
    exit 1
fi
