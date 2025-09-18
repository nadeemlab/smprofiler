# Development, maintenance, administration

1. <a href="#development-environment">Development environment</a>
2. <a href="#python-package">Python package</a>
3. <a href="#integration-tests">Integration tests</a>
4. <a href="#modules">Modules</a>
5. <a href="#test-managed-development">Test-managed development</a>
6. <a href="#smprofiler-tab-completion">`smprofiler` tab-completion</a>
7. <a href="#one-time-testing">One-time testing</a>
8. <a href="#new-workflows">Add a new workflow</a>
9. <a href="#one-test">Run one test</a>

## <a id="development-environment"></a> 1. Development 

Development tasks include:
- Determining up-to-date dependency requirements
- Releasing `smprofiler` to PyPI
- Building application container images
- Running integration/functional tests

## <a id="python-package"></a> 2. Python package

To release to PyPI use:

```sh
make release-package
```

`pyproject.toml` contains the package metadata, with only a few version constraints on dependencies.
Pinned versions for each dependency are listed separately in `requirements.txt`.

## <a id="integration-tests"></a> 3. Integration tests

The modules in this repository are built, tested, and deployed using `make` and Docker.

| Development environment software requirements              | Version required or tested under |
| ---------------------------------------------------------- | -------------------------------  |
| Unix-like operating system                                 | Darwin 20.6.0 and Ubuntu 24.04   |
| [bash](https://www.gnu.org/software/bash/)                 | 5.2.21                           |
| [Docker Engine](https://docs.docker.com/engine/install/)   | 27.5.1                           |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.32.4                           |
| [GNU Make](https://www.gnu.org/software/make/)             | 4.4.1                            |
| [uv](https://docs.astral.sh/uv/)                           | 0.5.29                           |
| [python](https://www.python.org/downloads/)                | 3.13                             |
| [toml](https://pypi.org/project/toml/)                     | 0.10.2                           |
| [sqlite3](https://sqlite.org/download.html)                | 3.45.1                           |
| [postgresql](https://www.postgresql.org/download/)         | 17                               |

A typical development workflow looks like:

1. Modify or add source files.
2. Add new tests.
3. `make clean`
<pre>
Checking that Docker daemon is running <span style="color:olive;">...</span><span style="color:olive;">......................................</span> <span style="font-weight:bold;color:green;">Running.</span>       <span style="color:purple;">(1s)</span>
Running docker compose rm (remove) <span style="color:olive;">...</span><span style="color:olive;">..........................................</span> <span style="font-weight:bold;color:green;">Down.</span>          <span style="color:purple;">(1s)</span>
</pre>
4. `make build-application-images`
<p align="center">
<img src="docs/image_assets/make_build_example.png"/>
</p>

5. `make test`
<p align="center">
<img src="docs/image_assets/make_test_example.png"/>
</p>

Optionally, if the images are ready to be released: `make build-and-push-docker-images`.

If the package source code is ready to be released to PyPI: `make release-package`.

## <a id="modules"></a> 4. Modules
The main functionality is provided by 4 modules designed to operate as services. Each module's source is wrapped in a Docker image.

| Module name     | Description |
| --------------- | ----------- |
| `apiserver`     | FastAPI application supporting queries over cell data. |
| `graphs`        | Command line tool to apply cell graph neural network models to data stored in an SMProfiler framework. |
| `ondemand`      | An optimized class-counting and other metrics-calculation program served by a custom TCP server. |
| `db`            | Data model/interface and PostgresQL database management SQL fragments. |
| `workflow`      | [Nextflow](https://www.nextflow.io)-orchestrated computation workflows. |

- *The `db` module is for testing only. A real PostgresQL database should generally not be deployed in a container.*

## <a id="test-managed-development"></a> 5. Test-managed development
Test scripts are located under `test/`.

These tests serve multiple purposes for us:
1. To verify preserved functionality during source code modification.
2. To exemplify typical usage of classes and functions, including how they are wrapped in a container and how that container is setup.

Each test is performed inside an isolated for-development-only `smprofiler`-loaded Docker container, in the presence of a running module-specific Docker composition that provides the given module's service as well as other modules' services (if needed).

## <a id="smprofiler-tab-completion"></a> 6. `smprofiler` tab completion
You might want to install `smprofiler` to your local machine in order to initiate database control actions, ETL, etc.

In this case bash completion is available that allows you to readily assess and find functionality provided at the command line. This reduces the need for some kinds of documentation, since such documentation is already folded in to the executables in such a way that it can be readily accessed.

After installation of the Python package, an entry point `smprofiler` is created. (Use `smprofiler-enable-completion` to manually install the completion to a shell profile file).
- `smprofiler [TAB]` yields the submodules which can be typed next.
- `smprofiler <module name> [TAB]` yields the commands provided by the given module.
- `smprofiler <module name> <command name> [TAB]` yields the `--help` text for the command.


## <a id="one-time-testing"></a> 7. One-time testing

Development often entails "throwaway" test scripts that you modify and run frequently in order to check your understanding of functionality and verify that it works as expected.

For this purpose, a pattern that has worked for me in this repository is:

1. Ensure at least one successful run of `make build-docker-images` at the top level of this repository's directory, for each module that you will use.
2. Go into the build are for a pertinent module: `cd build/<module name>`.
3. Create `throwaway_script.py`.
4. Setup the testing environment:
```sh
docker compose up -d
```
5. As many times as you need to, run your script with the following (replacing `<module name>`):
```
test_cmd="cd /mount_sources/<module name>/; python throwaway_script.py" ;
docker run \
  --rm \
  --network <module name>_isolated_temporary_test \
  --mount type=bind,src=$(realpath ..),dst=/mount_sources \
  -t nadeemlab-development/smprofiler-development:latest \
  /bin/bash -c "$test_cmd";
```
6. Tear down the testing environment when you're done:
```sh
docker compose down;
docker compose rm --force --stop;
```

You can of course also modify the testing environment, involving more or fewer modules, even docker containers from external images, by editing `compose.yaml`.

## <a id="new-workflows"></a> 8. Add a new workflow

The computation workflows are orchestrated with Nextflow, using the process definition script [`main_visitor.nf`](https://github.com/nadeemlab/SMProfiler/blob/main/smprofiler/workflow/assets/main_visitor.nf). "Visitor" refers to the visitor pattern, whereby the process steps access the database, do some reads, do some computations, and return some results by sending them to the database.

Each workflow consists of:
- "job" definition (in case the workflow calls for parallelization)
- initialization
- core jobs
- integration/wrap-up

**To make a new workflow**: copy the `phenotype_proximity` subdirectory to a sibling directory with a new name. Update the components accordingly, and update [`workflow/__init__.py`](https://github.com/nadeemlab/SMProfiler/blob/main/smprofiler/workflow/__init__.py) with a new entry for your workflow, to ensure that it is discovered. You'll also need to update [`pyproject.toml`](https://github.com/nadeemlab/SMProfiler/blob/main/pyproject.toml.unversioned) to declare your new subpackage.


## <a id="one-test"></a> 9. Run one test

It is often useful during development to run one test (e.g. a new test for a new feature).
This is a little tricky in our environment, which creates an elaborate test harness to simulate the production environment.
However, it can be done with the following snippet.

```bash
SHELL=$(realpath build/build_scripts/status_messages_only_shell.sh) \
MAKEFLAGS=--no-builtin-rules \
BUILD_SCRIPTS_LOCATION_ABSOLUTE=$(realpath build/build_scripts) \
MESSAGE='bash ${BUILD_SCRIPTS_LOCATION_ABSOLUTE}/verbose_command_wrapper.sh' \
DOCKER_ORG_NAME=nadeemlab \
DOCKER_REPO_PREFIX=smprofiler \
TEST_LOCATION_ABSOLUTE=$(realpath test) \
TEST_LOCATION=test \
  make --no-print-directory -C build/SUBMODULE_NAME test-../../test/SUBMODULE_NAME/module_tests/TEST_FILENAME
```
