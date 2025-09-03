.RECIPEPREFIX = >

MODULE_NAME := $(shell echo "verbose-shell-override" >/dev/null ; pwd | grep -o '[^/]\+$$' )

UNIT_TEST_FILES := $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/unit_tests/test_*.sh ) $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/unit_tests/test_*.py )
UNIT_TESTS := $(foreach test_file,$(UNIT_TEST_FILES),test-$(test_file))

MODULE_TEST_FILES := $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/module_tests/test_*.sh ) $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/module_tests/test_*.py )
MODULE_TESTS := $(foreach test_file,$(MODULE_TEST_FILES),test-$(test_file))

TESTS := ${UNIT_TESTS} ${MODULE_TESTS}

P := ${BUILD_SCRIPTS_LOCATION_ABSOLUTE}
UPDATE_STATUS = printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$(1)" "$(2)" | sqlite3 buildcache.sqlite3

.PHONY: setup-testing teardown-unit-testing teardown-module-testing

unit-tests: teardown-unit-testing
module-tests: teardown-module-testing
combined-tests: teardown-testing

setup-testing:
>@rm -f buildcache.sqlite3
>@${MESSAGE} start "$@" "graphs"
>@docker compose up -d ; bash ${P}/record_docker_logs.sh & \
    LOG_PID=$$!; \
	echo 'CREATE TABLE IF NOT EXISTS log_pids(pid int);' | sqlite3 buildcache.sqlite3 ; \
    if ps -p $$LOG_PID > /dev/null ; \
    then \
        echo "INSERT INTO log_pids VALUES ($$LOG_PID);" | sqlite3 buildcache.sqlite3 ; \
    fi ; \
    sleep 0.2 ; \
    bash ${P}/poll_container_readiness.sh \
     smprofiler-db---testing-only-graphs ; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Setup env." "Env not setup."

DOWN := docker compose stop -t 1 && docker compose down && docker compose rm --force --stop

teardown-unit-testing: ${UNIT_TESTS}
>@${MESSAGE} start "$@" "teardown ${MODULE_NAME}"
>@${DOWN}; status_code="$$?" ; $(call UPDATE_STATUS,$$status_code,$@) ;
>@bash ${P}/print_docker_logs.sh
>@${MESSAGE} end "$@" "Down." "Error."

teardown-module-testing: ${MODULE_TESTS}
>@${MESSAGE} start "$@" "teardown ${MODULE_NAME}"
>@${DOWN}; status_code="$$?" ; $(call UPDATE_STATUS,$$status_code,$@) ;
>@bash ${P}/print_docker_logs.sh
>@${MESSAGE} end "$@" "Down." "Error."

teardown-testing: ${TESTS}
>@${MESSAGE} start "$@" "teardown ${MODULE_NAME}"
>@${DOWN}; status_code="$$?" ; $(call UPDATE_STATUS,$$status_code,$@) ;
>@bash ${P}/print_docker_logs.sh
>@${MESSAGE} end "$@" "Down." "Error."

${TESTS}: setup-testing
>@test_target=$$(echo $@ | sed 's/..\/..\/${TEST_LOCATION}\/${MODULE_NAME}\///g') ; \
    test_script=$${test_target/test-/} ; \
    test_name=$${test_script/module_tests\/test_/} ; \
    test_name=$${test_name/unit_tests\/test_/} ; \
    extension=$$(echo $$test_name | grep -o "\.sh\|\.py$$" ) ; \
    test_name=$${test_name/$$extension/} ; \
    test_name=$$(echo "$$test_name" | tr '_' ' ' ) ; \
    ${MESSAGE} start "$@" "$$test_name"
>@test_target=$$(echo $@ | sed 's/..\/..\/${TEST_LOCATION}\/${MODULE_NAME}\///g') ; \
    test_script=$${test_target/test-/} ; \
    test_name=$${test_script/module_tests\/test_/} ; \
    test_name=$${test_name/unit_tests\/test_/} ; \
    extension=$$(echo $$test_name | grep -o "\.sh\|\.py$$" ) ; \
    executor=none-cmd ; \
    if [[ "$$extension" == ".py" ]]; then executor=${PYTHON}; fi ; \
    if [[ "$$extension" == ".sh" ]]; then executor=bash; fi ; \
    test_cmd="cd /mount_sources/graphs/; $$executor $$test_script" ; \
    docker run \
     --rm \
     --network ${MODULE_NAME}_isolated_temporary_test \
     --mount type=bind,src=${TEST_LOCATION_ABSOLUTE},dst=/mount_sources \
     -t ${DOCKER_ORG_NAME}-development/${DOCKER_REPO_PREFIX}-development:latest \
     /bin/bash -c "$$test_cmd" \
      --gpus all ; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Passed." "Failed."

clean:
>@rm -f buildcache.sqlite3
