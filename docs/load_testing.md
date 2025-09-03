# Load testing the application backend

Load testing helps to ensure that the whole application is functioning as expected and with adequate performance.

> [!NOTE]
> Recall that you can install the Python package `smprofiler` in several ways and in different environments:
> - In a virtual environment created with `python -m venv venv`.
> - In debug mode with the `-e` option: `python -m pip install -e .[all]`
> - From PyPI: `python -m pip install smprofiler[all]`
> - From a local build. Similar to: `python -m pip install dist/smprofiler-1.0.8-py3-none-any.whl[all]`

A load test procedure is provided as the SMProfiler command:

```sh
smprofiler db load-testing
```

To use it, you'll need access to your backend database from the terminal. The script prompts for database details and the API server you want to test. Typically these are either (i) both on a remote deployment, or (2) both in a local deployment.

The script performs 4 kinds of tests:

1. **Basic API availability**. These assess network connectivity and minimally-correct behavior of the server.
2. **Intermediate-load computation**. This pre-chosen example metric computation request results in only a handful of jobs in the job queue.
3. **Large job-set computation**. This example request is chosen to cause a relatively large number of jobs to be added to the job queue.
4. **Intensive job-set computation**. This example request is meant to test individual worker containers with the largest load they will experience during normal use, but without an exceptionally large number of jobs created.

The report for an example run is shown below. The real report is colorized in the terminal.

```txt
    Target database                                                             

Found database config files with correct format and validated credentials:
*0  /Users/username/.smprofiler_db.config
 1  /Users/username/.smprofiler_db.config.2

The previously-used credentials file is marked with *.

Select database config file [default selection 0]: 
Using /Users/username/.smprofiler_db.config

Select API server [default selection smprofiler.io/api]: 
Selected server: smprofiler.io/api
API version:     1.0.0
Number of pending jobs, including failed (abandoned, reached maximum retries):
orion_crc                          43
melanoma_cytof_ici                 42
breast_cancer_imc                 103
melanoma_intralesional_il2         56
luad_progression                  514
urothelial_ici                     51
melanoma_imc_tme_protein            0
head_and_neck_mpif                  1
gbm_imc                             0
brain_met_imc                       0
bone_marrow_aging                   0

Number of fresh pending jobs with no retries:
orion_crc                           0
melanoma_cytof_ici                  0
breast_cancer_imc                   0
melanoma_intralesional_il2          0
luad_progression                    0
urothelial_ici                      0
melanoma_imc_tme_protein            0
head_and_neck_mpif                  0
gbm_imc                             0
brain_met_imc                       0
bone_marrow_aging                   0

    Basic testing, simple queries                                               
 Retrieving http://smprofiler.io/api/study-summary/?study=Breast+cancer+IMC ... Done. 
 Retrieving http://smprofiler.io/api/channels/?study=Breast+cancer+IMC ... Done. 
 Retrieving http://smprofiler.io/api/phenotype-symbols/?study=Breast+cancer+IMC ... Done. 

3 basic requests:              121ms, 90ms, 234ms
Average response time:          148ms

50 basic requests with no waiting...
      
Average response time:          733ms
Total response time:            36.7s

    Intermediate non-trivial metrics computation, speed test                    
Test example is a phenotype fractions metric.
Dropping test example computed feature, if it exists.
 Retrieving http://smprofiler.io/api/phenotype-counts/?study=Breast+cancer+IMC&positive_marker=TWIST1&negative_marker=VWF ... Done. 
 polling job queue size... (time=29.8, size=0))

                                      Jobs cleared on average at 340.3 jobs / minute
      +-------------------------------------------------------------------------------------------------------------+
  160 |                                                  ***                                                        |
      |                                                     ***                     Number of jobs in queue ******* |
  140 |                                                        ***                                                  |
      |                                                           ***                                               |
  120 |                                                              **                                             |
      |                                                                **                                           |
  100 |                                                                  ***                                        |
      |                                                                     **                                      |
   80 |                                                                       ***                                   |
      |                                                                          ***                                |
      |                                                                             ***                             |
   60 |                                                                                ***                          |
      |                                                                                   ****                      |
   40 |                                                                                       ****                  |
      |                                                                                           ****              |
   20 |                                                                                               *****         |
      |                                                                                                    ******   |
    0 +-------------------------------------------------------------------------------------------------------------+
      0                 5                  10                15                 20                25
                                         Time since computation request (seconds)
Average clearance rate: 340.3 jobs per minute. 169 jobs in 29.8 seconds.

Cleaning up test example computed feature... Done.

    Large job-set metrics computation, speed test                               
Test examples are phenotype fractions metrics.
Dropping test example computed features, if they exists.
 Retrieving http://smprofiler.io/api/phenotype-counts/?study=LUAD+progression&positive_marker=MPO&negative_marker=KIT ... Done. 
 Retrieving http://smprofiler.io/api/phenotype-counts/?study=LUAD+progression&positive_marker=ITGAX&negative_marker=MPO ... Done. 
 Retrieving http://smprofiler.io/api/phenotype-counts/?study=LUAD+progression&positive_marker=KLRD1&negative_marker=CD14 ... Done. 
 Retrieving http://smprofiler.io/api/phenotype-counts/?study=LUAD+progression&positive_marker=KIT&negative_marker=MPO ... Done. 
 polling job queue size... (time=213.8, size=0)

                                      Jobs cleared on average at 573.1 jobs / minute
  2000 +------------------------------------------------------------------------------------------------------------+
       |             *****                                                                                          |
       |                  ******                                                    Number of jobs in queue ******* |
       |                        *****                                                                               |
       |                             ******                                                                         |
  1500 |                                   *******                                                                  |
       |                                          *****                                                             |
       |                                               *****                                                        |
       |                                                    *****                                                   |
  1000 |                                                         *****                                              |
       |                                                              ******                                        |
       |                                                                    *****                                   |
       |                                                                         *****                              |
       |                                                                              *****                         |
   500 |                                                                                   *******                  |
       |                                                                                          *****             |
       |                                                                                               ****         |
       |                                                                                                   *******  |
     0 +------------------------------------------------------------------------------------------------------------+
       0                        50                       100                      150                       200
                                         Time since computation request (seconds)
Average clearance rate: 573.1 jobs per minute. 2042 jobs in 213.8 seconds.

Cleaning up test example computed feature... Done.

    Intensive job-set metrics computation, speed test                           
Test example is a proximity metric.
Dropping test example computed features, if they exists.
 Retrieving http://smprofiler.io/api/request-spatial-metrics-computation-custom-phenotypes/?study=Orion+CRC&positive_marker=PDL1&negative_marker=SMA&positive_marker2=MKI67&negative_marker2=SMA&feature_class=proximity&radius=30.0 ... Done. 
 polling job queue size... (time=67.6, size=0)

                                      Jobs cleared on average at 36.4 jobs / minute
  40 +--------------------------------------------------------------------------------------------------------------+
     |                               *****                                                                          |
     |                                    ***********                               Number of jobs in queue ******* |
  35 |                                               *****                                                          |
     |                                                    *****                                                     |
  30 |                                                         **                                                   |
     |                                                           ***                                                |
  25 |                                                              ***                                             |
     |                                                                 **                                           |
  20 |                                                                   **                                         |
     |                                                                     **                                       |
  15 |                                                                       ***                                    |
     |                                                                          *****                               |
     |                                                                               **                             |
  10 |                                                                                 ****                         |
     |                                                                                     *****                    |
   5 |                                                                                          **                  |
     |                                                                                            ****              |
   0 +--------------------------------------------------------------------------------------------------------------+
     0               10               20              30               40              50               60
                                        Time since computation request (seconds)
Average clearance rate: 36.4 jobs per minute. 41 jobs in 67.6 seconds.

Cleaning up test example computed feature... Done.
```
