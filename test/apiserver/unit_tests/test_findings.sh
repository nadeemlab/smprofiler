
function do_query() {
    argument="$1"
    curl -s "$argument" ;
    if [ "$?" -gt 0 ];
    then
        echo "Error with apiserver query."
        curl "$argument"
        exit 1
    fi
}

do_query "http://smprofiler-apiserver-testing-apiserver:8080/study-findings/?study=Melanoma+intralesional+IL2"
