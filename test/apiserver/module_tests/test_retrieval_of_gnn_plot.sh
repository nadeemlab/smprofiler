
query="http://smprofiler-apiserver-testing-apiserver:8080/importance-fraction-plot/?study=Melanoma%20intralesional%20IL2"

curl -sf "$query" > _gnn.svg ;
curl -sf "$query" > _gnn.svg ;
if [ "$?" -gt 0 ];
then
    echo "Error with apiserver query for GNN plot."
    echo "$query"
    exit 1
fi

if [ ! -s _gnn.svg ] || ! grep -q "<svg" _gnn.svg; then
    echo "Error: Invalid or empty SVG file."
    exit 1
fi
