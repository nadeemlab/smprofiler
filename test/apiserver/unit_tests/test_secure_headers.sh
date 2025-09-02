
query=http://smprofiler-apiserver-testing-apiserver:8080/study-names/

curl -s $query 1>/dev/null 2>/dev/null;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

curl -s --verbose $query 2>&1 | grep '^< ' | grep -v 'date: ' | tr -d '\b\r' > response.txt

diff unit_tests/expected_headers_example.txt response.txt
status=$?
[ $status -eq 0 ] || (echo "API query for headers inspection failed."; )

if [ $status -eq 0 ];
then
    echo "Response headers were as expected:"
    echo
    cat response.txt
	rm response.txt
    exit 0
else
	cat response.txt
	rm response.txt
    exit 1
fi
