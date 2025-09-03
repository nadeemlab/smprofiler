
query=http://smprofiler-apiserver-testing-apiserver:8080/software-component-versions/

curl -s $query ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

curl -s $query | python -m json.tool > versions.json

diff unit_tests/expected_versions.json versions.json
status=$?
[ $status -eq 0 ] || (echo "API query for package versions failed."; )

if [ $status -eq 0 ];
then
	rm versions.json
    exit 0
else
	cat versions.json
	rm versions.json
    exit 1
fi
