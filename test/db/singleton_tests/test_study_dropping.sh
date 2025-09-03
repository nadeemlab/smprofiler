
smprofiler db status --database-config-file .smprofiler_db.config.container > current_counts.txt;
diff current_counts.txt module_tests/record_counts_1_2.txt
status="$?"
rm current_counts.txt
if [[ "$status" != "0" ]];
then
    echo "Wrong of records to begin with in this test."
    exit 1
fi

smprofiler db drop --study-name="Breast cancer IMC"  --database-config-file .smprofiler_db.config.container
if [[ "$?" != "0" ]];
then
    exit 1
fi

smprofiler db status --database-config-file .smprofiler_db.config.container > counts_after_drop.txt;

grep -v 'cell_phenotype\|chemical_species\|research_professional' counts_after_drop.txt > _counts_after_drop.txt
rm counts_after_drop.txt
grep -v 'cell_phenotype\|chemical_species\|research_professional' module_tests/record_counts1.txt > _record_counts1.txt

diff _counts_after_drop.txt _record_counts1.txt
if [[ "$?" != "0" ]];
then
    echo "Wrong number of counts after dropping."
    cat _counts_after_drop.txt
    rm _counts_after_drop.txt
    rm _record_counts1.txt
    exit 1
fi
rm _counts_after_drop.txt
rm _record_counts1.txt
