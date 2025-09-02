
profile_file=.temp_bash_profile
touch $profile_file
smprofiler-enable-completion --script-file=$profile_file
diff entry_point/expected_bash_completions_script.sh $profile_file
status=$?
[ $status -eq 0 ] || (echo "Completions script contents is not exactly as expected."; )
rm $profile_file
if [ $status -eq 0 ];
then
    exit 0
else
    exit 1
fi
