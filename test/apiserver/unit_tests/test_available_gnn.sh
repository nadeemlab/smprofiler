
query="http://smprofiler-apiserver-testing-apiserver:8080/available-gnn-metrics/?study=Melanoma+intralesional+IL2"

curl -s "$query" ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query."
    curl "$query"
    exit 1
fi
response=$(curl -s "$query")
if [[ "$response" != '{"plugins":["cg-gnn","graph-transformer"]}' ]];
then
    echo "API query for available GNN metrics failed."
    exit 1
fi
