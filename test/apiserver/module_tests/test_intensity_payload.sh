
blue="\033[36;2m"
green="\033[32m"
yellow="\033[33m"
red="\033[31m"
reset_code="\033[0m"

function test_cell_data_binary_intensity() {
    study="$1"
    sample="$2"
    filename="$3"
    query="http://smprofiler-apiserver-testing-apiserver:8080/cell-data-binary-intensity/?study=$study&sample=$sample"

    echo -e "Doing query $blue$query$reset_code ... "
    curl -s -H "Accept-Encoding: br" "$query"  > _celldata.bin.i;
    if [ "$?" -gt 0 ];
    then
        echo -e "${red}Error with apiserver query.$reset_code"
        echo "Result saved to file: _celldata.bin.i"
        exit 1
    fi

    cat _celldata.bin.i | brotli -d | xxd -e -b -c 30 > _celldata.dump.i
    rm _celldata.bin.i

    diff $filename _celldata.dump.i

    status=$?
    [ $status -eq 0 ] || (echo "API query for cell data failed, unexpected contents."; )
    if [ $status -eq 0 ];
    then
        rm _celldata.dump.i
        echo -e "${green}Artifact matches.$reset_code"
        echo
    else
        echo -e "${red}Some error with the diff command.$reset_code"
        echo "Erroneous file saved to: _celldata.dump.i"
        exit 1
    fi
}

test_cell_data_binary_intensity "Melanoma+intralesional+IL2" "lesion+0_1" module_tests/celldata.dump2
test_cell_data_binary_intensity "Melanoma+intralesional+IL2" "UMAP+virtual+sample" module_tests/celldata.dump3
