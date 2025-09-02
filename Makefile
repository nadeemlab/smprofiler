.RECIPEPREFIX = >

help:
>@echo '  This program is used for development and testing tasks.'
>@echo ' '
>@echo '  make release-package'
>@echo '    Build the Python package wheel and push it to PyPI.'
>@echo ' '
>@echo '  make build-and-push-application-images'
>@echo '    Build the application Docker images (API server and computation workers)'
>@echo '    and push them to DockerHub repositories.'
>@echo ' '
>@echo '  make force-rebuild-data-loaded-images'
>@echo '    Rebuild the data-preloaded Docker images. This is relatively'
>@echo '    long-running and so is left out of the typical test target'
>@echo '    fulfillment process.'
>@echo ' '
>@echo '  make test'
>@echo '    Do unit and module tests.'
>@echo ' '
>@echo '  make -j10 test'
>@echo '    Do all tests with e.g. 10 cores in parallel.'
>@echo ' '
>@echo '  make [unit | module]-test-[apiserver | graphs | ondemand | db | workflow]'
>@echo '    Do only the unit or module tests for the indicated module.'
>@echo ' '
>@echo '  make clean'
>@echo '    Attempt to remove all build or partial-build artifacts.'
>@echo '    This will also try to start the Docker daemon if it is not already running.'
>@echo ' '
>@echo '  make clean-docker-images'
>@echo '    Aggressively removes the Docker images created here.'
>@echo '    It makes use `docker system prune`, which might delete other images, so use at your own risk.'
>@echo '    This target does not attempt to remove external images pulled as base images, however.'
>@echo '    Note that normal `make clean` does not attempt to remove Docker images at all.'
>@echo ' '
>@echo '  make help'
>@echo '    Show this text.'
>@echo ' '
>@echo 'Use VERBOSE=1 to send command outputs to STDOUT rather than log files.'
>@echo 'Use NOCACHE=1 to cause docker build commands to rebuild each cached layer.'
>@echo ' '

MAKEFLAGS += --warn-undefined-variables
MAKEFLAGS += --no-builtin-rules

PACKAGE_NAME := smprofiler
export PYTHON := python
export BUILD_SCRIPTS_LOCATION_ABSOLUTE := ${PWD}/build/build_scripts
SCRIPTS := ${BUILD_SCRIPTS_LOCATION_ABSOLUTE}
SOURCE_LOCATION := ${PACKAGE_NAME}
PLUGIN_SOURCE_LOCATION := plugin
BUILD_LOCATION := build
BUILD_LOCATION_ABSOLUTE := ${PWD}/build
export TEST_LOCATION := test
export TEST_LOCATION_ABSOLUTE := ${PWD}/${TEST_LOCATION}
LOCAL_USERID := $(shell id -u)
VERSION := $(shell cat pyproject.toml | grep 'version = ' | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
export WHEEL_FILENAME := ${PACKAGE_NAME}-${VERSION}-py3-none-any.whl
WHEEL := ${WHEEL_FILENAME}
export MESSAGE := bash ${SCRIPTS}/verbose_command_wrapper.sh

export DOCKER_ORG_NAME := nadeemlab
export DOCKER_REPO_PREFIX := smprofiler
REPO_DEV := ${DOCKER_ORG_NAME}-development/${DOCKER_REPO_PREFIX}-development
REPO := ${DOCKER_ORG_NAME}/${DOCKER_REPO_PREFIX}
export DOCKER_SCAN_SUGGEST:=false
SUBMODULES := apiserver graphs ondemand db workflow
DOCKERIZED_SUBMODULES := apiserver db ondemand
PLUGINS := graph_processing/cg-gnn graph_processing/graph-transformer
CUDA_PLUGINS := graph_processing/cg-gnn

DOCKERFILES := $(foreach submodule,$(DOCKERIZED_SUBMODULES),${BUILD_LOCATION}/$(submodule)/Dockerfile)

DOCKER_BUILD_SUBMODULE_TARGETS := $(foreach submodule,$(DOCKERIZED_SUBMODULES),${BUILD_LOCATION_ABSOLUTE}/$(submodule)/docker.built)
DOCKER_BUILD_PLUGIN_TARGETS := $(foreach plugin,$(PLUGINS),${BUILD_LOCATION_ABSOLUTE}/plugins/$(plugin).docker.built)
DOCKER_BUILD_PLUGIN_CUDA_TARGETS := $(foreach plugin,$(CUDA_PLUGINS),${BUILD_LOCATION_ABSOLUTE}/plugins/$(plugin)-cuda.docker.built)
_UNPUSHABLES := db
PUSHABLE_SUBMODULES := $(filter-out ${_UNPUSHABLES},$(DOCKERIZED_SUBMODULES))
DOCKER_PUSH_SUBMODULE_TARGETS := $(foreach submodule,$(PUSHABLE_SUBMODULES),docker-push-${PACKAGE_NAME}/$(submodule))
DOCKER_PUSH_DEV_SUBMODULE_TARGETS := $(foreach submodule,$(DOCKERIZED_SUBMODULES),docker-push-dev-${PACKAGE_NAME}/$(submodule))
DOCKER_PUSH_PLUGIN_TARGETS := $(foreach plugin,$(PLUGINS),docker-push-${PACKAGE_NAME}/$(plugin))
DOCKER_PUSH_DEV_PLUGIN_TARGETS := $(foreach plugin,$(PLUGINS),docker-push-dev-${PACKAGE_NAME}/$(plugin))
DOCKER_PUSH_PLUGIN_CUDA_TARGETS := $(foreach plugin,$(CUDA_PLUGINS),docker-push-${PACKAGE_NAME}/$(plugin)-cuda)
DOCKER_PUSH_DEV_PLUGIN_CUDA_TARGETS := $(foreach plugin,$(CUDA_PLUGINS),docker-push-dev-${PACKAGE_NAME}/$(plugin)-cuda)
MODULE_TEST_TARGETS := $(foreach submodule,$(SUBMODULES),module-test-$(submodule))
UNIT_TEST_TARGETS := $(foreach submodule,$(SUBMODULES),unit-test-$(submodule))
SINGLETON_TEST_TARGETS := $(foreach submodule,$(SUBMODULES),singleton-test-$(submodule))
COMBINED_TEST_TARGETS := $(foreach submodule,$(SUBMODULES),combined-test-$(submodule))
DLI := force-rebuild-data-loaded-image
P := ${BUILD_LOCATION_ABSOLUTE}
.PHONY: help release-package check-for-pypi-credentials print-source-files build-and-push-docker-images ${DOCKER_PUSH_SUBMODULE_TARGETS} ${DOCKER_PUSH_PLUGIN_TARGETS} ${DOCKER_PUSH_PLUGIN_CUDA_TARGETS} build-docker-images test module-tests ${MODULE_TEST_TARGETS} ${UNIT_TEST_TARGETS} clean clean-files docker-compositions-rm clean-network-environment generic-smprofiler-push-target data-loaded-images-push-target ensure-plugin-submodules-are-populated before_all_tests

export DB_SOURCE_LOCATION_ABSOLUTE := ${PWD}/${SOURCE_LOCATION}/db
export DB_BUILD_LOCATION_ABSOLUTE := ${PWD}/${BUILD_LOCATION}/db

PACKAGE_SOURCE_FILES := pyproject.toml $(shell find ${SOURCE_LOCATION} -type f)
DEPENDENCY_LISTS := requirements.txt requirements.apiserver.txt requirements.ondemand.txt
EXTRAS_requirements.txt := "[all]"
EXTRAS_requirements.apiserver.txt := "[apiserver]"
EXTRAS_requirements.ondemand.txt := "[ondemand]"

export SHELL := ${SCRIPTS}/status_messages_only_shell.sh

# By default, no verbose log output is shown. For the default "help" target, make an exception.
ifdef VERBOSE
    export .SHELLFLAGS := -c -super-verbose
else
    ifeq ('${MAKECMDGOALS}', '')
        export .SHELLFLAGS := -c -super-verbose
    else
        ifeq ('${MAKECMDGOALS}', 'help')
            export .SHELLFLAGS := -c -super-verbose
        else
            export .SHELLFLAGS := -c -not-super-verbose
        endif
    endif
endif

ifdef NOCACHE
export NO_CACHE_FLAG := --no-cache
else
export NO_CACHE_FLAG := 
endif

UPDATE_STATUS = printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$(1)" "$(2)" | sqlite3 buildcache.sqlite3

release-package: development-image check-for-pypi-credentials
>@${MESSAGE} start "$@" "Uploading smprofiler==${VERSION} to PyPI"
>@cp ~/.pypirc .
>@docker run \
     -u ${LOCAL_USERID} \
     --rm \
     --mount \
     type=bind,src=${PWD},dst=/mount_sources \
     -t ${REPO_DEV}:latest \
     /bin/bash -c 'cd /mount_sources; PYTHONDONTWRITEBYTECODE=1 python -m twine upload --config-file .pypirc --repository ${PACKAGE_NAME} dist/${WHEEL} ' ;\
    status_code=$$?; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Uploaded." "Error."
>@rm -f .pypirc

check-for-pypi-credentials:
>@${MESSAGE} start "$@" "Checking for PyPI credentials in ~/.pypirc for smprofiler"
>@${PYTHON} ${SCRIPTS}/check_for_credentials.py pypi ; \
    status_code=$$?; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Found." "Not found."

development-image-prerequisites-installed: ${DEPENDENCY_LISTS} ${SCRIPTS}/development_prereqs.Dockerfile
>@${MESSAGE} start "$@" "Building development image precursor"
>@cp ${SCRIPTS}/.dockerignore . 
>@docker build \
     ${NO_CACHE_FLAG} \
     --rm \
     -f ${SCRIPTS}/development_prereqs.Dockerfile \
     -t ${REPO_DEV}-prereqs:latest \
     . ; \
    status_code=$$?; \
    if [[ "$$status_code" == "0" ]]; \
    then \
        touch development-image-prerequisites-installed ; \
    fi ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Built." "Build failed."
>@rm -f .dockerignore

initialize_message_cache:
>@source ${SCRIPTS}/message_cache.sh; rm buildcache.sqlite3; initialize_message_cache;

development-image: ${PACKAGE_SOURCE_FILES} ${SCRIPTS}/development.Dockerfile development-image-prerequisites-installed
>@${MESSAGE} start "$@" "Building development image"
>@cp ${SCRIPTS}/.dockerignore . 
>@docker build \
     ${NO_CACHE_FLAG} \
     --rm \
     --no-cache \
     --pull=false \
     -f ${SCRIPTS}/development.Dockerfile \
     -t ${REPO_DEV}:latest \
     --build-arg WHEEL_FILENAME=${WHEEL} \
     . ; \
    status_code=$$? ; \
    if [[ "$$status_code" == "0" ]]; \
    then \
        if [ ! -d dist/ ]; then mkdir dist ; fi; \
        docker run \
         --rm \
         -v \
         $$(pwd)/dist:/buffer \
         ${REPO_DEV} \
         /bin/sh -c "cp dist/${WHEEL} /buffer; chown ${LOCAL_USERID}:${LOCAL_USERID} /buffer/*; "; \
        touch development-image ; \
    fi; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Built." "Build failed."
>@rm -f .dockerignore

pyproject.toml.unversioned: pyproject.toml
>@if [[ ! -f pyproject.toml.unversioned ]]; then grep -v 'version=' pyproject.toml > pyproject.toml.unversioned; fi;

${DEPENDENCY_LISTS}: pyproject.toml.unversioned ${SCRIPTS}/determine_prerequisites.sh | initialize_message_cache
>@${MESSAGE} start "$@" "Determining $@"
>@extras=${EXTRAS_$@}; \
    ${SCRIPTS}/determine_prerequisites.sh "$$extras" $@; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Complete." "Determination failed."

build-and-push-application-images: ${DOCKER_PUSH_SUBMODULE_TARGETS}

build-and-push-docker-images: ${DOCKER_PUSH_SUBMODULE_TARGETS} ${DOCKER_PUSH_PLUGIN_TARGETS} ${DOCKER_PUSH_PLUGIN_CUDA_TARGETS} generic-smprofiler-push-target data-loaded-images-push-target

build-and-push-docker-images-dev: ${DOCKER_PUSH_DEV_SUBMODULE_TARGETS} ${DOCKER_PUSH_DEV_PLUGIN_TARGETS} ${DOCKER_PUSH_DEV_PLUGIN_CUDA_TARGETS}

${DOCKER_PUSH_SUBMODULE_TARGETS}: ${DOCKER_BUILD_SUBMODULE_TARGETS} check-for-docker-credentials
>@submodule_directory=$$(echo $@ | sed 's/^docker-push-//g') ; \
    submodule_name=$$(echo $$submodule_directory | sed 's/smprofiler\///g') ; \
    repository_name=${REPO}-$$submodule_name ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name"
>@submodule_directory=$$(echo $@ | sed 's/^docker-push-//g') ; \
    submodule_name=$$(echo $$submodule_directory | sed 's/smprofiler\///g') ; \
    echo "$$submodule_name"; \
    repository_name=${REPO}-$$submodule_name ; \
    echo "$$repository_name"; \
    docker push $$repository_name:${VERSION} ; \
    exit_code1=$$?; \
    docker push $$repository_name:latest ; \
    exit_code2=$$?; \
    status_code=$$(( exit_code1 + exit_code2 )) ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

${DOCKER_PUSH_DEV_SUBMODULE_TARGETS}: build-docker-images check-for-docker-credentials
>@submodule_directory=$$(echo $@ | sed 's/^docker-push-dev-//g') ; \
    submodule_name=$$(echo $$submodule_directory | sed 's/smprofiler\///g') ; \
    repository_name=${REPO}-$$submodule_name ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name"
>@submodule_directory=$$(echo $@ | sed 's/^docker-push-dev-//g') ; \
    submodule_name=$$(echo $$submodule_directory | sed 's/smprofiler\///g') ; \
    echo "$$submodule_name"; \
    repository_name=${REPO}-$$submodule_name ; \
    echo "$$repository_name"; \
    docker push $$repository_name:dev ; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

${DOCKER_PUSH_PLUGIN_TARGETS}: build-docker-images check-for-docker-credentials
>@plugin_name=$$(basename $@) ; \
    repository_name=${REPO}-$$plugin_name ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name"
>@plugin_name=$$(basename $@) ; \
    repository_name=${REPO}-$$plugin_name ; \
    plugin_relative_directory=$$(dirname $@ | sed 's,docker-push-${PACKAGE_NAME}\/,,g')/$$plugin_name ; \
    source_directory=${PLUGIN_SOURCE_LOCATION}/$$plugin_relative_directory ; \
    echo "$$plugin_name"; \
    echo "$$repository_name"; \
    docker push $$repository_name:${VERSION} ; \
    exit_code1=$$?; \
    docker push $$repository_name:latest ; \
    exit_code2=$$?; \
    status_code=$$(( exit_code1 + exit_code2 )) ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

${DOCKER_PUSH_DEV_PLUGIN_TARGETS}: build-docker-images check-for-docker-credentials
>@plugin_name=$$(basename $@) ; \
    repository_name=${REPO}-$$plugin_name ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name"
>@plugin_name=$$(basename $@) ; \
    repository_name=${REPO}-$$plugin_name ; \
    plugin_relative_directory=$$(dirname $@ | sed 's,docker-push-dev-${PACKAGE_NAME}\/,,g')/$$plugin_name ; \
    source_directory=${PLUGIN_SOURCE_LOCATION}/$$plugin_relative_directory ; \
    echo "$$plugin_name"; \
    echo "$$repository_name"; \
    docker push $$repository_name:dev ; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

${DOCKER_PUSH_PLUGIN_CUDA_TARGETS}: build-docker-images check-for-docker-credentials
>@plugin_name=$$(basename $@ -cuda) ; \
    repository_name=${REPO}-$$plugin_name ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name:cuda"
>@plugin_name=$$(basename $@ -cuda) ; \
    repository_name=${REPO}-$$plugin_name ; \
    plugin_relative_directory=$$(dirname $@ | sed 's,docker-push-${PACKAGE_NAME}\/,,g')/$$plugin_name ; \
    source_directory=${PLUGIN_SOURCE_LOCATION}/$$plugin_relative_directory ; \
    echo "$$plugin_name"; \
    echo "$$repository_name"; \
    docker push $$repository_name:cuda-${VERSION} ; \
    exit_code1=$$?; \
    docker push $$repository_name:cuda-latest ; \
    exit_code2=$$?; \
    status_code=$$(( exit_code1 + exit_code2 )) ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

${DOCKER_PUSH_DEV_PLUGIN_CUDA_TARGETS}: build-docker-images check-for-docker-credentials
>@plugin_name=$$(basename $@ -cuda) ; \
    repository_name=${REPO}-$$plugin_name ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name:cuda"
>@plugin_name=$$(basename $@ -cuda) ; \
    repository_name=${REPO}-$$plugin_name ; \
    plugin_relative_directory=$$(dirname $@ | sed 's,docker-push-dev-${PACKAGE_NAME}\/,,g')/$$plugin_name ; \
    source_directory=${PLUGIN_SOURCE_LOCATION}/$$plugin_relative_directory ; \
    echo "$$plugin_name"; \
    echo "$$repository_name"; \
    docker push $$repository_name:cuda-dev ; \
    status_code=$$? ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

generic-smprofiler-push-target: build-docker-images check-for-docker-credentials
>@repository_name=${REPO} ; \
    ${MESSAGE} start "$@" "Pushing Docker container $$repository_name"
>@repository_name=${REPO} ; \
    docker tag ${REPO_DEV}:latest $$repository_name:${VERSION} ; \
    docker push $$repository_name:${VERSION} ; \
    exit_code1=$$?; \
    docker tag ${REPO_DEV}:latest $$repository_name:latest ; \
    docker push $$repository_name:latest ; \
    exit_code2=$$?; \
    status_code=$$(( exit_code1 + exit_code2 )) ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

data-loaded-images-push-target:
>@${MESSAGE} start "$@" "Pushing preloaded data Docker containers"
>@repository_name_prefix=${REPO}-db-preloaded ; \
    codes=0 ; \
    for suffix in 1 2 1and2 1small 1smallnointensity; \
    do \
        existing=$$repository_name_prefix-$$suffix:latest ; \
        tag=$$repository_name_prefix-$$suffix:${VERSION} ; \
        docker tag $$existing $$tag ; \
        docker push $$existing ; \
        exitcode="$$?" ; \
        codes=$$(( codes + exitcode )) ; \
        docker push $$tag ; \
        exitcode="$$?" ; \
        codes=$$(( codes + exitcode )) ; \
    done; \
    status_code="$$codes" ; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Pushed." "Not pushed."

check-for-docker-credentials:
>@${MESSAGE} start "$@" "Checking for Docker credentials in ~/.docker/config.json"
>@${PYTHON} ${SCRIPTS}/check_for_credentials.py docker ; status_code="$$?"; if [[ "$$status_code" == "0" ]]; then touch check-for-docker-credentials; fi; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Found." "Not found."

ensure-plugin-submodules-are-populated:
>@git submodule update --init --recursive

build-application-images: ${DOCKER_BUILD_SUBMODULE_TARGETS}

build-docker-images: ${DOCKER_BUILD_SUBMODULE_TARGETS} ${DOCKER_BUILD_PLUGIN_TARGETS} ${DOCKER_BUILD_PLUGIN_CUDA_TARGETS}

# Build the Docker container for each submodule by doing the following:
#   1. Identify the submodule being built
#   2. Emit a message about it
#   3. Copy relevant files to the build folder
#   4. docker build the container
#   5. Remove copied files
${DOCKER_BUILD_SUBMODULE_TARGETS}: pyproject.toml.unversioned ${DOCKERFILES} development-image check-docker-daemon-running check-for-docker-credentials
>@submodule_directory=$$(echo $@ | sed 's/\/docker.built//g') ; \
    dockerfile=$${submodule_directory}/Dockerfile ; \
    submodule_name=$$(echo $$submodule_directory | sed 's,${BUILD_LOCATION_ABSOLUTE}\/,,g') ; \
    repository_name=${REPO}-$$submodule_name ; \
    ${MESSAGE} start "$@" "Building Docker image $$repository_name"
>@submodule_directory=$$(echo $@ | sed 's/\/docker.built//g') ; \
    dockerfile=$${submodule_directory}/Dockerfile ; \
    submodule_name=$$(echo $$submodule_directory | sed 's,${BUILD_LOCATION_ABSOLUTE}\/,,g') ; \
    repository_name=${REPO}-$$submodule_name ; \
    cp pyproject.toml.unversioned $$submodule_directory/pyproject.toml ; \
    cp ${DEPENDENCY_LISTS} $$submodule_directory ; \
    cp dist/${WHEEL} $$submodule_directory ; \
    cp $$submodule_directory/Dockerfile ./Dockerfile ; \
    cp ${SCRIPTS}/.dockerignore . ; \
    docker build \
     ${NO_CACHE_FLAG} \
     -f ./Dockerfile \
     -t ${DOCKER_REPO_PREFIX}-$$submodule_name \
     -t $$repository_name:${VERSION} \
     -t $$repository_name:latest \
     -t $$repository_name:dev \
     --build-arg version=${VERSION} \
     --build-arg service_name=$$submodule_name \
     --build-arg WHEEL_FILENAME=${WHEEL} \
     $$submodule_directory ; status_code="$$?" ; \
    if [[ "$$status_code" == "0" ]]; \
    then \
        touch $@ ;\
    fi; \
    $(call UPDATE_STATUS,$$status_code,$@) ;
>@${MESSAGE} end "$@" "Built." "Build failed."
>@submodule_directory=$$(echo $@ | sed 's/\/docker.built//g') ; \
    rm $$submodule_directory/${WHEEL} ; \
    rm ./Dockerfile ; \
    rm ./.dockerignore ; \

${DOCKER_BUILD_PLUGIN_TARGETS}: check-docker-daemon-running check-for-docker-credentials ensure-plugin-submodules-are-populated
>@plugin_name=$$(basename $@ .docker.built) ; \
    repository_name=${REPO}-$$plugin_name ; \
    ${MESSAGE} start "$@" "Building Docker image $$repository_name"
>@plugin_name=$$(basename $@ .docker.built) ; \
    repository_name=${REPO}-$$plugin_name ; \
    plugin_relative_directory=$$(dirname $@ | sed 's,${BUILD_LOCATION_ABSOLUTE}\/plugins\/,,g')/$$plugin_name ; \
    source_directory=${PLUGIN_SOURCE_LOCATION}/$$plugin_relative_directory ; \
    plugin_directory=$$(dirname $@)/$$plugin_name ; \
    mkdir -p $$plugin_directory ; \
    cp -r $$source_directory/* $$plugin_directory ; \
    cp $$(dirname $@)/$$(basename $@ .docker.built).dockerfile ./Dockerfile ; \
    cp ${SCRIPTS}/.dockerignore . ; \
    docker build \
     ${NO_CACHE_FLAG} \
     -f ./Dockerfile \
     -t $$repository_name:${VERSION} \
     -t $$repository_name:latest \
     -t $$repository_name:dev \
     --build-arg version=${VERSION} \
     --build-arg service_name=$$plugin_name \
     $$plugin_directory ; status_code="$$?" ; \
    if [[ "$$(cat status_code)" == "0" ]]; \
    then \
        touch $@ ; \
    fi; \
    printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$@" | sqlite3 buildcache.sqlite3 ;
>@${MESSAGE} end "$@" "Built." "Build failed."
>@plugin_name=$$(basename $@ .docker.built) ; \
    plugin_directory=$$(dirname $@)/$$plugin_name ; \
    rm -r $$plugin_directory ; \

${DOCKER_BUILD_PLUGIN_CUDA_TARGETS}: check-docker-daemon-running check-for-docker-credentials ensure-plugin-submodules-are-populated
>@plugin_name=$$(basename $@ -cuda.docker.built) ; \
    repository_name=${REPO}-$$plugin_name ; \
    ${MESSAGE} start "$@" "Building Docker image $$repository_name:cuda"
>@plugin_name=$$(basename $@ -cuda.docker.built) ; \
    repository_name=${REPO}-$$plugin_name ; \
    plugin_relative_directory=$$(dirname $@ | sed 's,${BUILD_LOCATION_ABSOLUTE}\/plugins\/,,g')/$$plugin_name ; \
    source_directory=${PLUGIN_SOURCE_LOCATION}/$$plugin_relative_directory ; \
    plugin_directory=$$(dirname $@)/$$plugin_name-cuda ; \
    mkdir -p $$plugin_directory ; \
    cp $$source_directory/* $$plugin_directory ; \
    cp $$(dirname $@)/$$(basename $@ .docker.built).dockerfile ./Dockerfile ; \
    cp ${SCRIPTS}/.dockerignore . ; \
    docker build \
     ${NO_CACHE_FLAG} \
     -f ./Dockerfile \
     -t $$repository_name:cuda-${VERSION} \
     -t $$repository_name:cuda-latest \
     -t $$repository_name:cuda-dev \
     --build-arg version=${VERSION} \
     --build-arg service_name=$$plugin_name \
     $$plugin_directory ; status_code="$$?" ; \
    if [[ "$$status_code" == "0" ]]; \
    then \
        touch $@ ; \
    fi ; \
    printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$@" | sqlite3 buildcache.sqlite3 ;
>@${MESSAGE} end "$@" "Built." "Build failed."
>@plugin_name=$$(basename $@ -cuda.docker.built) ; \
    plugin_directory=$$(dirname $@)/$$plugin_name-cuda ; \
    rm -r $$plugin_directory ; \

check-docker-daemon-running:
>@${MESSAGE} start "$@" "Checking that Docker daemon is running"
>@docker stats --no-stream > /dev/null ; status_code="$$?" ; \
    printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$@" | sqlite3 buildcache.sqlite3 ; \
    ${MESSAGE} end "$@" "Running." "Not running." ; \
    if [ $$status_code -gt 0 ] ; \
    then \
        task="Attempting to start Docker daemon"; \
        ${MESSAGE} start "$$task" "$$task" ; \
        bash ${SCRIPTS}/start_docker_daemon.sh ; status_code="$$?" ; \
        printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$$task" | sqlite3 buildcache.sqlite3 ; \
        ${MESSAGE} end "Attempting to start Docker daemon" "Running." "Failed to start." ; \
    fi ; \
    touch check-docker-daemon-running ;

# Some dependencies to force serial processing (build environments would conflict if concurrent)
clean-network-environment: initialize_message_cache
check-docker-daemon-running: initialize_message_cache
before_all_tests: clean-network-environment
>@${MESSAGE} start "start timing" "Start timing"

${P}/db/docker.built: before_all_tests
${P}/apiserver/docker.built: ${P}/db/docker.built
${P}/ondemand/docker.built: ${P}/apiserver/docker.built
data-loaded-image-1and2: ${P}/ondemand/docker.built
data-loaded-image-1: data-loaded-image-1and2
data-loaded-image-1small: data-loaded-image-1
data-loaded-image-1smallnointensity: data-loaded-image-1small

DATA_IMAGES := data-loaded-image-1smallnointensity data-loaded-image-1small data-loaded-image-1 data-loaded-image-1and2

test: ${COMBINED_TEST_TARGETS}
>@printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "0" "start timing" | sqlite3 buildcache.sqlite3 ;
>@${MESSAGE} end "start timing" "Total time:" "Error computing time."

module-tests: ${MODULE_TEST_TARGETS}

${MODULE_TEST_TARGETS}: development-image ${DATA_IMAGES} ${DOCKER_BUILD_SUBMODULE_TARGETS} before_all_tests
>@submodule_directory=$$(echo $@ | sed 's/^module-test-/${BUILD_LOCATION}\//g') ; \
    ${MAKE} SHELL=$(SHELL) --no-print-directory -C $$submodule_directory module-tests ;

unit-tests: ${UNIT_TEST_TARGETS}

${UNIT_TEST_TARGETS}: development-image ${DATA_IMAGES} ${DOCKER_BUILD_SUBMODULE_TARGETS} before_all_tests
>@submodule_directory=$$(echo $@ | sed 's/^unit-test-/${BUILD_LOCATION}\//g') ; \
    ${MAKE} SHELL=$(SHELL) --no-print-directory -C $$submodule_directory unit-tests ;

${SINGLETON_TEST_TARGETS}: development-image ${DATA_IMAGES} ${DOCKER_BUILD_SUBMODULE_TARGETS} before_all_tests
>@submodule_directory=$$(echo $@ | sed 's/^singleton-test-/${BUILD_LOCATION}\//g') ; \
    ${MAKE} SHELL=$(SHELL) --no-print-directory -C $$submodule_directory singleton-tests ;

${COMBINED_TEST_TARGETS}: development-image ${DATA_IMAGES} ${DOCKER_BUILD_SUBMODULE_TARGETS} before_all_tests
>@submodule_directory=$$(echo $@ | sed 's/^combined-test-/${BUILD_LOCATION}\//g') ; \
    ${MAKE} SHELL=$(SHELL) --no-print-directory -C $$submodule_directory combined-tests ;

# The below explicitly checks whether the docker image already exists locally.
# If so, not rebuilt. To trigger rebuild, use "make clean-docker-images" first,
# or directly force-rebuild-data-loaded-images .
data-loaded-image-%: ${BUILD_LOCATION_ABSOLUTE}/db/docker.built ${SCRIPTS}/import_test_dataset%.sh development-image
>@${MESSAGE} start "$@" "Building test-data-loaded smprofiler-db image ($*)"
>@cp ${SCRIPTS}/.dockerignore . 
>@source ${SCRIPTS}/check_image_exists.sh; \
    exists=$$(check_image_exists ${REPO}-db-preloaded-$*); \
    if [[ "$$exists" == "no" ]]; \
    then \
        docker container create --name temporary-smprofiler-db-preloading --network host -e POSTGRES_PASSWORD=postgres -e PGDATA=.postgres/pgdata ${REPO}-db:latest ; \
        docker container start temporary-smprofiler-db-preloading && \
        bash ${SCRIPTS}/poll_container_readiness_direct.sh temporary-smprofiler-db-preloading && \
        pipeline_cmd="cd /working_dir; cp -r /mount_sources/build .; cp -r /mount_sources/test .; bash build/build_scripts/import_test_dataset$*.sh "; \
        docker container run \
        -i \
        --rm \
        -e SQLITE_MOCK_DATABASE=1 \
        --network container:temporary-smprofiler-db-preloading \
        --mount type=bind,src=${PWD},dst=/mount_sources \
        --mount type=tmpfs,destination=/working_dir \
        -t ${REPO_DEV}:latest \
        /bin/bash -c \
        "$$pipeline_cmd" ; status_code="$$?" && \
        docker commit temporary-smprofiler-db-preloading ${REPO}-db-preloaded-$*:latest && \
        docker container rm --force temporary-smprofiler-db-preloading ; \
    fi; \
    if [[ "$$status_code" == "0" ]]; \
    then \
        touch data-loaded-image-$* ; \
    fi ; \
    if [[ "$$status_code" == "" ]]; then status_code=0; fi ; \
    printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$@" | sqlite3 buildcache.sqlite3 ;
>@${MESSAGE} end "$@" "Built." "Build failed."
>@rm -f .dockerignore

force-rebuild-data-loaded-images: ${DLI}-1 ${DLI}-1and2 ${DLI}-1small ${DLI}-1smallnointensity

force-rebuild-data-loaded-image-%: ${BUILD_LOCATION_ABSOLUTE}/db/docker.built ${SCRIPTS}/import_test_dataset%.sh
>@${MESSAGE} start "$@" "Rebuilding test-data-loaded smprofiler-db image ($*)"
>@cp ${SCRIPTS}/.dockerignore . 
>@source ${SCRIPTS}/check_image_exists.sh; \
    docker container create --name temporary-smprofiler-db-preloading --network host -e POSTGRES_PASSWORD=postgres -e PGDATA=.postgres/pgdata ${REPO}-db:latest ; \
    docker container start temporary-smprofiler-db-preloading && \
    bash ${SCRIPTS}/poll_container_readiness_direct.sh temporary-smprofiler-db-preloading && \
    pipeline_cmd="cd /working_dir; cp -r /mount_sources/build .; cp -r /mount_sources/test .; bash build/build_scripts/import_test_dataset$*.sh "; \
    docker run \
    --rm \
    --network container:temporary-smprofiler-db-preloading \
    --mount type=bind,src=${PWD},dst=/mount_sources \
    --mount type=tmpfs,destination=/working_dir \
    -t ${REPO_DEV}:latest \
    /bin/bash -c \
    "$$pipeline_cmd" ; status_code="$$?" && \
    docker commit temporary-smprofiler-db-preloading ${REPO}-db-preloaded-$*:latest && \
    docker container rm --force temporary-smprofiler-db-preloading ; \
    if [[ "$$status_code" == "0" ]]; \
    then \
        touch data-loaded-image-$* ; \
    fi ; \
    printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$@" | sqlite3 buildcache.sqlite3 ;
>@${MESSAGE} end "$@" "Rebuilt." "Rebuild failed."
>@rm -f .dockerignore

clean: clean-files clean-files-docker-daemon clean-network-environment

clean-network-environment: | clean-files-docker-daemon

clean-files-docker-daemon:
>@rm -f check-docker-daemon-running
>@rm -f check-for-docker-credentials

clean-files:
>@rm -rf ${PACKAGE_NAME}.egg-info/
>@rm -rf dist/
>@rm -f ${BUILD_LOCATION}/*/.initiation_message_size
>@rm -f ${BUILD_LOCATION}/*/.current_time.txt
>@for submodule in ${SUBMODULES} ; do \
        submodule_directory=${BUILD_LOCATION}/$$submodule ; \
        ${MAKE} SHELL=$(SHELL) --no-print-directory -C $$submodule_directory clean ; \
        rm -f $$submodule_directory/docker.built ; \
    done
>@rm -f Dockerfile
>@rm -f .dockerignore
>@rm -rf smprofiler.egg-info/
>@rm -rf __pycache__/
>@rm -f ${DEPENDENCY_LISTS}
>@rm -f development-image
>@rm -f development-image-prerequisites-installed
>@rm -f ${DATA_IMAGES}
>@rm -f file_manifest.tsv.bak
>@rm -f .nextflow.log; rm -f .nextflow.log.*; rm -rf .nextflow/; rm -f configure.sh; rm -f run.sh; rm -f main.nf; rm -f nextflow.config; rm -rf work/; rm -rf results/
>@rm -rf ${BUILD_LOCATION}/lib
>@rm -f build/*/log_of_build.log
>@rm -f log_of_build.log
>@rm -f pyproject.toml.unversioned

docker-compositions-rm: check-docker-daemon-running
>@${MESSAGE} start "$@" "Running docker compose rm (remove)"
>@docker compose --project-directory ./build/apiserver/ rm --force --stop ; status_code1="$$?" ; \
    docker compose --project-directory ./build/ondemand/ rm --force --stop ; status_code2="$$?" ; \
    docker compose --project-directory ./build/db/ rm --force --stop ; status_code3="$$?" ; \
    status_code=$$(( status_code1 + status_code2 + status_code3 + status_code4 + status_code5 )) ; \
    printf 'UPDATE times SET status_code=%s WHERE activity="%s";' "$$status_code" "$@" | sqlite3 buildcache.sqlite3 ;
>@docker container rm --force temporary-smprofiler-db-preloading
>@${MESSAGE} end "$@" "Down." "Error."

clean-network-environment: docker-compositions-rm

clean-docker-images:
>@docker system prune -f
>@for tag in $$(docker image ls | grep ${DOCKER_ORG_NAME} | awk '{print $$1":"$$2}'); \
    do \
    docker image rm $$tag; \
    done;
>@docker system prune -f
