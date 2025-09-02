
query="http://smprofiler-apiserver-testing-apiserver:8080/phenotype-counts-batch/"
data="$(cat module_tests/criteria_specs.json | python -m json.tool --compact)"
curl -H "Content-Type: application/json" --data "$data" -s $query ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl $query
    exit 1
fi

curl -H "Content-Type: application/json" --data "$data" -s $query | python -m json.tool > c.json

python -c 'import sys; from json import loads; j=loads(open("c.json", "rt", encoding="utf-8").read()); sys.exit(1) if len(j)!=2 else print("2 responses, OK.")'

status=$?
rm c.json
[ $status -eq 0 ] || (echo "API query for batch phenotype counts failed."; )
exit $status
