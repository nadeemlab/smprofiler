

blue="\033[36;2m"
green="\033[32m"
yellow="\033[33m"
red="\033[31m"
reset_code="\033[0m"

function normalize_floats() {
    filename="$1"
    sed -r 's/(\.[0-9][0-9][0-9])[0-9]+/\1/g' "$filename"
}

function test_proximity() {
    p1="$1"
    p2="$2"
    r="$3"
    filename="$4"
    query="http://smprofiler-apiserver-testing-apiserver:8080/request-spatial-metrics-computation-custom-phenotypes/?study=Melanoma%20intralesional%20IL2&feature_class=proximity&$p1&$p2&radius=$r"
    start=$SECONDS
    while (( SECONDS - start < 120 )); do
        echo -en "Doing query $blue$query$reset_code ... "
        curl -s "$query" > _proximity.json;
        if [ "$?" -gt 0 ];
        then
            echo -e "${red}Error with apiserver query.$reset_code"
            cat _proximity.json
            rm _proximity.json
            exit 1
        fi
        pending=$(python -c 'import json; o=json.loads(open("_proximity.json").read()); print(o["is_pending"])')
        if [[ "$pending" == "False" ]];
        then
            echo
            echo -en "${yellow}Metrics available.$reset_code "
            cat _proximity.json | python -m json.tool > proximity.json
            rm _proximity.json
            break
        else
            waitperiod=1
            echo "Still pending. Waiting ${waitperiod} seconds to poll for metrics availability... "
            sleep $waitperiod
        fi
    done

    normalize_floats "$filename" > n1.json
    normalize_floats proximity.json > n2.json
    diff n1.json n2.json
    status=$?
    rm n1.json n2.json
    [ $status -eq 0 ] || (echo "API query for proximity metrics failed."; )
    if [ $status -eq 0 ];
    then
        rm proximity.json
        echo -e "${green}Artifact matches.$reset_code"
        echo
    else
        echo -e "${red}Some error with the diff command.$reset_code"
        cat proximity.json
        rm proximity.json
        exit 1
    fi
}

test_proximity "positive_marker=B2M&negative_marker=" "positive_marker2=CD4&negative_marker2=" 60 module_tests/expected_proximity.json
test_proximity "positive_marker=B7H3&negative_marker=" "positive_marker2=CD3&positive_marker2=CD4&negative_marker2=CD8&negative_marker2=FOXP3&negative_marker2=CD20&negative_marker2=CD56&negative_marker2=SOX10&" 60 module_tests/expected_proximity2.json
test_proximity "positive_marker=CD8&negative_marker=" "positive_marker2=MHCI&negative_marker2=" 125 module_tests/expected_proximity3.json
test_proximity "positive_marker=CD3&positive_marker=CD8&negative_marker=CD4&negative_marker=FOXP3&negative_marker=CD20&negative_marker=CD56&negative_marker=SOX10&" "positive_marker2=PD1&negative_marker2=" 125 module_tests/expected_proximity4.json
