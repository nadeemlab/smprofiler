
study="Melanoma+intralesional+IL2"

rm -f db1.db db2.db db3.db

query="http://smprofiler-apiserver-testing-apiserver:8080/sqlite/?study=$study"
curl -s "$query" > db1.db
status=$?
if [ $status -gt 0 ];
then
    echo "Problem with query: $query" >&2
    exit $status
fi;

query="http://smprofiler-apiserver-testing-apiserver:8080/sqlite/?study=$study&no_feature_values="
curl -s "$query" > db2.db
status=$?
if [ $status -gt 0 ];
then
    echo "Problem with query: $query" >&2
    exit $status
fi;

query="http://smprofiler-apiserver-testing-apiserver:8080/sqlite/?study=$study&no_feature_values=&no_feature_specifications="
curl -s "$query" > db3.db
status=$?
if [ $status -gt 0 ];
then
    echo "Problem with query: $query" >&2
    exit $status
fi;
