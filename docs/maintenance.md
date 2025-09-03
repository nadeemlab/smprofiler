# Development, maintenance, administration

1. <a href="#development-environment">Development environment</a>
2. <a href="#python-package">Python package</a>
2. <a href="#integration-tests">Integration tests</a>
3. <a href="#modules">Modules</a>
4. <a href="#test-managed-development">Test-managed development</a>
5. <a href="#smprofiler-tab-completion">`smprofiler` tab-completion</a>
6. <a href="#throwaway-testing">Throwaway testing</a>
7. <a href="#new-workflows">Add a new workflow</a>

## <a id="development-environment"></a> 1. Development environment

For SMProfiler development tasks, we use:

|                                                            | Version required or tested under |
| ---------------------------------------------------------- | -------------------------------  |
| [bash](https://www.gnu.org/software/bash/)                 | 5.2.21                           |
| [Docker Engine](https://docs.docker.com/engine/install/)   | 27.5.1                           |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.32.4                           |
| [GNU Make](https://www.gnu.org/software/make/)             | 4.4.1                            |
| [uv](https://docs.astral.sh/uv/)                           | 0.5.29                           |
| [python](https://www.python.org/downloads/)                | 3.13                             |

These tasks include:
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

## <a id="integration-tests"></a> 2. Integration tests

The modules in this repository are built, tested, and deployed using `make` and Docker.

| Development environment software requirements              | Version required or tested under |
| ---------------------------------------------------------- | -------------------------------  |
| Unix-like operating system                                 | Darwin 20.6.0 and Ubuntu 20.04   |
| [GNU Make](https://www.gnu.org/software/make/)             | 4.2.1                            |
| [Docker Engine](https://docs.docker.com/engine/install/)   | 20.10.17                         |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.10.2                           |
| [bash](https://www.gnu.org/software/bash/)                 | >= 4                             |
| [python](https://www.python.org/downloads/)                | >=3.7 <3.12                      |
| [postgresql](https://www.postgresql.org/download/)         | 13.4                             |
| [toml](https://pypi.org/project/toml/)                     | 0.10.2                           |

A typical development workflow looks like:

1. Modify or add source files.
2. Add new tests.
3. `$ make clean`
<pre>
Checking that Docker daemon is running <span style="color:olive;">...</span><span style="color:olive;">......................................</span> <span style="font-weight:bold;color:green;">Running.</span>       <span style="color:purple;">(1s)</span>
Running docker compose rm (remove) <span style="color:olive;">...</span><span style="color:olive;">..........................................</span> <span style="font-weight:bold;color:green;">Down.</span>          <span style="color:purple;">(1s)</span>
</pre>
4. `$ make test`

```txt
Creating pyproject.toml ........................................................ Created.       (0s)
Building development image precursor ........................................... Built.         (0s)
Building development image ..................................................... Built.         (1s)
Building apiserver Dockerfile .................................................. Built.         (0s)
Building graphs Dockerfile ..................................................... Built.         (0s)
Building ondemand Dockerfile ................................................... Built.         (0s)
Building db Dockerfile ......................................................... Built.         (0s)
Building workflow Dockerfile ................................................... Built.         (0s)
Checking for Docker credentials in ~/.docker/config.json ....................... Found.         (0s)
Building Docker image nadeemlab/smprofiler-db ......................................... Built.         (6s)
Building test-data-loaded smprofiler-db image (1small) ................................ Built.         (0s)
Building test-data-loaded smprofiler-db image (1) ..................................... Built.         (0s)
Building test-data-loaded smprofiler-db image (1and2) ................................. Built.         (1s)
Building Docker image nadeemlab/smprofiler-apiserver .................................. Built.         (5s)
Building Docker image nadeemlab/smprofiler-graphs ..................................... Built.         (6s)
Building Docker image nadeemlab/smprofiler-ondemand ................................... Built.         (6s)
Building Docker image nadeemlab/smprofiler-workflow ................................... Built.         (6s)
Running docker compose rm (remove) ............................................. Down.          (1s)
apiserver (setup testing environment) .......................................... Setup.         (4s)
  study names .................................................................. Passed.        (1s)
  record counts ................................................................ Passed.        (4s)
  API internal basic database accessor ......................................... Passed.        (1s)
  expressions in db ............................................................ Passed.        (1s)
apiserver (teardown testing environment) ....................................... Down.          (1s)
graphs (setup testing environment) ............................................. Setup.         (2s)
  image runs properly .......................................................... Passed.        (1s)
graphs (teardown testing environment) .......................................... Down.          (1s)
ondemand (setup testing environment) ........................................... Setup.         (4s)
  binary expression viewer ..................................................... Passed.        (1s)
  intensity values imported .................................................... Passed.        (4s)
ondemand (teardown testing environment) ........................................ Down.          (0s)
db (setup testing environment) ................................................. Setup.         (3s)
  guess channels from object files ............................................. Passed.        (1s)
  drop recreate database constraints ........................................... Passed.        (13s)
  shapefile polygon extraction ................................................. Passed.        (1s)
db (teardown testing environment) .............................................. Down.          (0s)
workflow (setup testing environment) ........................................... Setup.         (3s)
  centroid pulling ............................................................. Passed.        (3s)
  feature matrix extraction .................................................... Passed.        (26s)
  stratification pulling ....................................................... Passed.        (2s)
  signature cell set subsetting ................................................ Passed.        (1s)
  sample stratification ........................................................ Passed.        (1s)
workflow (teardown testing environment) ........................................ Down.          (1s)
Building test-data-loaded smprofiler-db image (1smallnointensity) ..................... Built.         (0s)
apiserver (setup testing environment) .......................................... Setup.         (5s)
  phenotype criteria ........................................................... Passed.        (0s)
  proximity .................................................................... Passed.        (4s)
  phenotype summary ............................................................ Passed.        (0s)
  retrieval of umap plots ...................................................... Passed.        (5s)
  retrieval of hi res umap ..................................................... Passed.        (1s)
  study summary retrieval ...................................................... Passed.        (0s)
  counts query delegation edge cases ........................................... Passed.        (1s)
apiserver (teardown testing environment) ....................................... Down.          (1s)
graphs (teardown testing environment) .......................................... Down.          (0s)
ondemand (setup testing environment) ........................................... Setup.         (4s)
  expression data caching ...................................................... Passed.        (13s)
  class counts cohoused datasets ............................................... Passed.        (1s)
  edge cases few markers ....................................................... Passed.        (1s)
  single signature count query ................................................. Passed.        (0s)
ondemand (teardown testing environment) ........................................ Down.          (1s)
db (setup testing environment) ................................................. Setup.         (3s)
  basic health of database ..................................................... Passed.        (5s)
  expression table indexing .................................................... Passed.        (13s)
  record counts cohoused datasets .............................................. Passed.        (4s)
  fractions assessment ......................................................... Passed.        (4s)
db (teardown testing environment) .............................................. Down.          (0s)
workflow (setup testing environment) ........................................... Setup.         (3s)
  proximity pipeline ........................................................... Passed.        (95s)
  umap plot creation ........................................................... Passed.        (56s)
workflow (teardown testing environment) ........................................ Down.          (1s)
```

Optionally, if the images are ready to be released:

- `$ make build-and-push-docker-images`

<pre>
Checking for Docker credentials in ~/.docker/config.json <span style="color:olive;">...</span><span style="color:olive;">....................</span> <span style="font-weight:bold;color:green;">Found.</span>         <span style="color:purple;">(0s)</span>
Pushing Docker container nadeemlab/smprofiler-apiserver <span style="color:olive;">...</span><span style="color:olive;">............................</span> <span style="font-weight:bold;color:green;">Pushed.</span>        <span style="color:purple;">(16s)</span>
Pushing Docker container nadeemlab/smprofiler-ondemand <span style="color:olive;">...</span><span style="color:olive;">.............................</span> <span style="font-weight:bold;color:green;">Pushed.</span>        <span style="color:purple;">(15s)</span>
Pushing Docker container nadeemlab/smprofiler-db <span style="color:olive;">...</span><span style="color:olive;">...................................</span> <span style="font-weight:bold;color:green;">Pushed.</span>        <span style="color:purple;">(23s)</span>
Pushing Docker container nadeemlab/smprofiler-workflow <span style="color:olive;">...</span><span style="color:olive;">.............................</span> <span style="font-weight:bold;color:green;">Pushed.</span>        <span style="color:purple;">(27s)</span>
</pre>

If the package source code is ready to be released to PyPI:

- `$ make release-package`

<pre>
Checking for PyPI credentials in ~/.pypirc for smprofiler <span style="color:olive;">...</span><span style="color:olive;">......</span> <span style="font-weight:bold;color:green;">Found.</span>         <span style="color:purple;">(0s)</span>
Uploading smprofiler==0.11.0 to PyPI <span style="color:olive;">...</span><span style="color:olive;">...........................</span> <span style="font-weight:bold;color:green;">Uploaded.</span>      <span style="color:purple;">(3s)</span>
</pre>

## <a id="python-package"></a> 2. Python package
The source code is contained in one Python package, `smprofiler`. The package metadata uses the declarative `pyproject.toml` format.

## <a id="modules"></a> 3. Modules
The main functionality is provided by 4 modules designed to operate as services. Each module's source is wrapped in a Docker image.

| Module name     | Description |
| --------------- | ----------- |
| `apiserver`     | FastAPI application supporting queries over cell data. |
| `graphs`        | Command line tool to apply cell graph neural network models to data stored in an SMProfiler framework. |
| `ondemand`      | An optimized class-counting and other metrics-calculation program served by a custom TCP server. |
| `db`            | Data model/interface and PostgresQL database management SQL fragments. |
| `workflow`      | [Nextflow](https://www.nextflow.io)-orchestrated computation workflows. |

- *The `db` module is for testing only. A real PostgresQL database should generally not be deployed in a container.*

## <a id="test-managed-development"></a> 4. Test-managed development
Test scripts are located under `test/`.

These tests serve multiple purposes for us:
1. To verify preserved functionality during source code modification.
2. To exemplify typical usage of classes and functions, including how they are wrapped in a container and how that container is setup.

Each test is performed inside an isolated for-development-only `smprofiler`-loaded Docker container, in the presence of a running module-specific Docker composition that provides the given module's service as well as other modules' services (if needed).

## <a id="smprofiler-tab-completion"></a> 5. `smprofiler` tab completion
You might want to install `smprofiler` to your local machine in order to initiate database control actions, ETL, etc.

In this case bash completion is available that allows you to readily assess and find functionality provided at the command line. This reduces the need for some kinds of documentation, since such documentation is already folded in to the executables in such a way that it can be readily accessed.

After installation of the Python package, an entry point `smprofiler` is created. (Use `smprofiler-enable-completion` to manually install the completion to a shell profile file).
- `smprofiler [TAB]` yields the submodules which can be typed next.
- `smprofiler <module name> [TAB]` yields the commands provided by the given module.
- `smprofiler <module name> <command name> [TAB]` yields the `--help` text for the command.


## <a id="throwaway-testing"></a> 6. Throwaway testing

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

## <a id="new-workflows"></a> 7. Add a new workflow

The computation workflows are orchestrated with Nextflow, using the process definition script [`main_visitor.nf`](https://github.com/nadeemlab/SMProfiler/blob/main/smprofiler/workflow/assets/main_visitor.nf). "Visitor" refers to the visitor pattern, whereby the process steps access the database, do some reads, do some computations, and return some results by sending them to the database.

Each workflow consists of:
- "job" definition (in case the workflow calls for parallelization)
- initialization
- core jobs
- integration/wrap-up

**To make a new workflow**: copy the `phenotype_proximity` subdirectory to a sibling directory with a new name. Update the components accordingly, and update [`workflow/__init__.py`](https://github.com/nadeemlab/SMProfiler/blob/main/smprofiler/workflow/__init__.py) with a new entry for your workflow, to ensure that it is discovered. You'll also need to update [`pyproject.toml`](https://github.com/nadeemlab/SMProfiler/blob/main/pyproject.toml.unversioned) to declare your new subpackage.


## <a id="one-test"></a> 8. Do one test

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
