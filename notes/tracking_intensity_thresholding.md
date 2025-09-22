
Sep 22 2025

# Case A:
- in smprofiler.io
- Bone marrow aging
- sample: WCM1
- phenotype: CD15+
- total cells: 46213
- CD15+ cells: 19115
- Fraction CD15+ cells: 0.4227

# Case B:
- local reproduction of backend computation:
  * counts_computer.py
  * count_snippet.py
- Bone marrow aging
- feature specification 17 (already specified in DB, for CD15+)
- sample: WCM1
- Note: DB quantitiative feature value record matches Case A: (468, 17, WCM1, 19115)
- CD15+ cells: 19115 (same as Case A)
- run log:
```txt
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ _get_count called
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 0: 0000000000000000000000000000000000000000000000100010010000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 1: 0000000000000000000000000000000000000000000000100010010000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 2: 0000000000000000000000000000000000000000000000100000110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 3: 0000000000000000000000000000000000000000000000111001110000000011
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 4: 0000000000000000000000000000000000000000000000100010010000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 5: 0000000000000000000000000000000000000000000000100000110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 6: 0000000000000000000000000000000000000000000000100000110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 7: 0000000000000000000000000000000000000000000001000010010000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 8: 0000000000000000000000000000000000000000000001000010010000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 9: 0000000000000000000000000000000000000000000000100000010000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 10: 0000000000000000000000000000000000000000000010010011010000000011
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 11: 0000000000000000000000000000000000000000000000100000110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 12: 0000000000000000000000000000000000000000000000100010110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 13: 0000000000000000000000000000000000000000000010010010000000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 14: 0000000000000000000000000000000000000000000001000010000000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ ...
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46212: 0000000000000000000000000000000000000000000000100010110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46211: 0000000000000000000000000000000000000000000001000000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46210: 0000000000000000000000000000000000000000000001010000110000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46209: 0000000000000000000000000000000000000000000010010000110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46208: 0000000000000000000000000000000000000000000001010100100000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46207: 0000000000000000000000000000000000000000000000110000110000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46206: 0000000000000000000000000000000000000000000010010010100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46205: 0000000000000000000000000000000000000000000000100000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46204: 0000000000000000000000000000000000000000000000110000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46203: 0000000000000000000000000000000000000000000000110000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46202: 0000000000000000000000000000000000000000000100001000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46201: 0000000000000000000000000000000000000000000010010100000000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46200: 0000000000000000000000000000000000000000000001000000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46199: 0000000000000000000000000000000000000000000000100000100000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ Case 46198: 0000000000000000000000000000000000000000000001000010100000000001
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ positives_mask: 0000000000000000000000000000000000000000000000010000000000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ negatives_mask: 0000000000000000000000000000000000000000000000000000000000000000
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ len(array_phenotype): 46213
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ sum(array_phenoytpe | positives_mask == array_phenotype): 19115
09-22 17:35:24 [ INFO  ] ondemand.computers.counts_computer                 ┃ sum(array_phenoytpe | negatives_mask == array_phenotype): 46213
09-22 17:35:24 [WARNING] 112 ondemand.computers.generic_job_computer        ┃ (17, WCM1) value already exists, can't insert 19115
```

# Case C:
- Run curation script portion which computes dichotomized values, save threshold (or use previously saved?) for specific channel.
- threshold.csv entry:
```txt
sample,channel,final_threshold,singly_optimized,original_mean
WCM1,CD15,30.515562807722702,30.515562807722702,29.731426239013672
```
- file_manifest.tsv mentions: 0.csv is WCM1
- line count 0.csv: 46214
- saved CD15 intensity column separate
- thresholds.csv mentions: WCM1, CD15, 30.515562807722702
- with given 0.csv values and given saved threshold for CD15, get total positives: 28134 (so, discrepant)
- after recomputed thresholds.csv...
- positives: 28611 (still discrepant)

# Rerunning threshold optimization
- works from original hdf5 dataframe
- uses smprofiler threshold optimization, a per-sample optimization starting from given signature-defined assignments
- results don't seem to be much different. specifically:
  - WCM1, CD15: 29.64304469917444

# Compare recreated generated_artifacts with saved intensity data, as well as S3 bucket snapshots

