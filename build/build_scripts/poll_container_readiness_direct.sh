
declare -A expectedmessages
expectedmessages[temporary-smprofiler-db-preloading]="database system is ready to accept connections"

container_name=$1

echo "Looking for:"
echo "${expectedmessages[$container_name]}"

counter=0
while :
do
    echo "Attempt $counter to check readiness of container."
    available="yes"

    docker container logs $container_name 1>/dev/null 2>/dev/null
    if [ $? -gt 0 ];
    then
    	echo "Error polling container".
    	exit 1
    fi

    docker container logs $container_name | grep --color "${expectedmessages[$container_name]}"
    if [ $? -gt 0 ];
    then
        available="no"
    fi

    if [[ $available == "yes" ]];
    then
        echo "Container is ready"
        exit
    fi
    counter=$(( counter + 1 ))
    if [[ $counter -gt 30 ]];
    then
        echo "Container readiness checking timed out after 15 seconds"
        exit 1
    fi
    sleep 0.5
done

echo "Container may not be ready"
exit 1