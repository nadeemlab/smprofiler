
blue="\033[36;2m"
green="\033[32m"
yellow="\033[33m"
red="\033[31m"
reset_code="\033[0m"

function test_cell_data_binary() {
    study="$1"
    sample="$2"
    filename="$3"
    query="http://smprofiler-apiserver-testing-apiserver:8080/cell-data-binary/?study=$study&sample=$sample"

    echo -e "Doing query $blue$query$reset_code ... "
    curl -s "$query"  > _celldata_u.bin;
    if [ "$?" -gt 0 ];
    then
        echo -e "${red}Error with apiserver query.$reset_code"
        echo "Result saved to file: _celldata_u.bin"
        exit 1
    fi

    cat _celldata_u.bin | tail -c +21 | xxd -e -b -c 20 > _celldata_u.dump
    rm _celldata_u.bin

    lines1=$(wc -c < $filename)
    lines2=$(wc -c < _celldata_u.dump)
    if [[ "$lines1" != "$lines2" ]];
    then
        status=1
    else
        status=0
    fi;

    [ $status -eq 0 ] || (echo "API query for cell data failed, unexpected byte count: $lines2 (expected $lines1)."; )
    if [ $status -eq 0 ];
    then
        rm _celldata_u.dump
        echo -e "${green}Artifact matches well enough.$reset_code"
        echo
    else
        echo -e "${red}Some error with the diff command.$reset_code"
        echo "Erroneous file saved to: _celldata_u.dump"
        exit 1
    fi
}

test_cell_data_binary "Melanoma+intralesional+IL2" "UMAP+virtual+sample" module_tests/celldata.umap.dump
