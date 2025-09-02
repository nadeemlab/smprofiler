
query='http://smprofiler-apiserver-testing-apiserver:8080/sqlite/?study=Melanoma+intralesional+IL2'

curl -s --verbose "$query" 2>&1 | head -n24 | grep '^< ' | grep -v 'date: ' | tr -d '\b\r' > response.txt

diff unit_tests/expected_headers_example2.txt response.txt
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
