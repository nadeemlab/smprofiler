

blue="\033[36;2m"
green="\033[32m"
yellow="\033[33m"
red="\033[31m"
reset_code="\033[0m"

function normalize_floats() {
    filename="$1"
    sed -r 's/(\.[0-9][0-9][0-9])[0-9]+/\1/g' "$filename"
}

function test_proximity_batch() {
    query="http://smprofiler-apiserver-testing-apiserver:8080/batch-request-spatial-metrics-computation-custom-phenotypes/"
    curl -X POST -d @batch_specifications.json "$query" --header "Content-Type:application/json" | python -m json.tool > batch_result.json
    start=$SECONDS
    while (( SECONDS - start < 120 )); do
        echo -en "Doing POST request $blue$query$reset_code ... "
        curl -X POST -d @batch_specifications.json "$query" --header "Content-Type:application/json"
        curl -X POST -d @batch_specifications.json "$query" --header "Content-Type:application/json" | python -m json.tool > batch_result.json
        pending=$(python -c 'import json; o=json.loads(open("batch_result.json").read()); print(any(r["is_pending"] for r in o))')
        if [[ "$pending" == "False" ]];
        then
            echo
            echo -en "${yellow}Metrics available.$reset_code "
            cat batch_result.json
            break
        else
            waitperiod=1
            echo "Still pending. Waiting ${waitperiod} seconds to poll for metrics availability... "
            sleep $waitperiod
        fi
    done

    normalize_floats batch_result.json > n1.json
    normalize_floats expected_batch_result.json > n2.json

    diff n2.json n1.json
    status=$?
    rm n1.json n2.json batch_result.json
    [ $status -eq 0 ] || (echo "API query for batch proximity metrics failed."; )
}

test_proximity_batch