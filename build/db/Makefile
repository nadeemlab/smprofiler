.RECIPEPREFIX = >

MODULE_NAME := $(shell echo "verbose-shell-override" >/dev/null ; pwd | grep -o '[^/]\+$$' )

SINGLETON_TEST_FILES := ../../${TEST_LOCATION}/${MODULE_NAME}/singleton_tests/test_study_dropping.sh
SINGLETON_TESTS := $(foreach test_file,$(SINGLETON_TEST_FILES),test-$(test_file))

UNIT_TEST_FILES := $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/unit_tests/test_*.sh ) $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/unit_tests/test_*.py )
UNIT_TESTS := $(foreach test_file,$(UNIT_TEST_FILES),test-$(test_file))

MODULE_TEST_FILES := $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/module_tests/test_*.sh ) $(wildcard ../../${TEST_LOCATION}/${MODULE_NAME}/module_tests/test_*.py )
MODULE_TESTS := $(foreach test_file,$(MODULE_TEST_FILES),test-$(test_file))

# TESTS := ${UNIT_TESTS} ${MODULE_TESTS} ${SINGLETON_TESTS}
TESTS := ${UNIT_TESTS} ${MODULE_TESTS}

# Ensures that the test for database record numbers (for clean image) is run first, before new
# records are created by subsequent tests.
INITIAL_TEST := test-../../${TEST_LOCATION}/${MODULE_NAME}/module_tests/test_record_counts_cohoused_datasets.sh
OTHER_TESTS := $(filter-out ${INITIAL_TEST},${TESTS})
${OTHER_TESTS}: ${INITIAL_TEST}

P := ${BUILD_SCRIPTS_LOCATION_ABSOLUTE}
UPDATE_STATUS = printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$(1)" "$(2)" | sqlite3 buildcache.sqlite3

DATA_MODEL_SOURCE_LOCATION := ${DB_SOURCE_LOCATION_ABSOLUTE}/data_model

schema.sql:
>@docker run \
     --rm \
     --mount type=bind,src=${DB_BUILD_LOCATION_ABSOLUTE},dst=/mount_sources \
     -t ${DOCKER_ORG_NAME}-development/${DOCKER_REPO_PREFIX}-development:latest \
     /bin/bash -c \
     'cd /mount_sources; adiscstudies dump-schema > schema.sql' ;

.PHONY: setup-testing teardown-unit-testing teardown-module-testing teardown-testing

singleton-tests: teardown-singleton-testing
unit-tests: teardown-unit-testing
module-tests: teardown-module-testing
combined-tests: teardown-testing

setup-testing:
>@rm -f buildcache.sqlite3
>@${MESSAGE} start "$@" "db"
>@docker compose up -d ; bash ${P}/record_docker_logs.sh & \
    LOG_PID=$$!; \
	echo 'CREATE TABLE IF NOT EXISTS log_pids(pid int);' | sqlite3 buildcache.sqlite3 ; \
    if ps -p $$LOG_PID > /dev/null ; \
    then \
        echo "INSERT INTO log_pids VALUES ($$LOG_PID);" | sqlite3 buildcache.sqlite3 ; \
    fi ; \
    sleep 0.2 && \
    bash ${P}/poll_container_readiness.sh \
     smprofiler-db---testing-only-db ; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Setup env." "Env not setup."

teardown-singleton-testing: ${SINGLETON_TESTS}
>@${MESSAGE} start "$@" "teardown db"
>@docker compose stop -t 1 && docker compose down && docker compose rm --force --stop ; status_code="$$?" ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Down." "Error."

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
    if [[ "$$extension" == ".py" ]]; then executor=python; fi ; \
    if [[ "$$extension" == ".sh" ]]; then executor=bash; fi ; \
    test_cmd="cd /mount_sources/db/ && $$executor $$test_script" ; \
    docker run \
     --rm \
     --network ${MODULE_NAME}_isolated_temporary_test \
     --mount type=bind,src=${TEST_LOCATION_ABSOLUTE},dst=/mount_sources \
     -t ${DOCKER_ORG_NAME}-development/${DOCKER_REPO_PREFIX}-development:latest \
     /bin/bash -c "$$test_cmd && exit $$?"; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Passed." "Failed."

clean:
>@rm -rf schema.sql
>@rm -f err_log.*.txt
>@for f in dlogs.db.txt dlogs.api.txt dlogs.od.txt; do rm -f $$f; done;
>@rm -f buildcache.sqlite3
