
query="http://smprofiler-apiserver-testing-apiserver:8080/phenotype-symbols/?study=Melanoma+intralesional+IL2"

curl -s $query ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

curl -s $query | python -m json.tool > symbols.json

diff unit_tests/expected_phenotype_symbols.json symbols.json
status=$?
[ $status -eq 0 ] || (echo "API query for phenotype symbols failed."; )

if [ $status -eq 0 ];
then
	rm symbols.json
    exit 0
else
	cat symbols.json
	rm symbols.json
    exit 1
fi
