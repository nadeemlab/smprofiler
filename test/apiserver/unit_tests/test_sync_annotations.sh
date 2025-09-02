
smprofiler db sync-annotations unit_tests/example_channel_annotations.json --database-config-file=.smprofiler_db.config.container

query=http://smprofiler-apiserver-testing-apiserver:8080/channel-annotations/
curl -s "$query" | python -m json.tool > _a.json
cat _a.json
diff _a.json expected_a.json
status=$?
rm _a.json
if [ $status -gt 0 ];
then
    exit $status
fi;

query=http://smprofiler-apiserver-testing-apiserver:8080/channel-aliases/
curl -s "$query" | python -m json.tool > _b.json
cat _b.json
diff _b.json expected_b.json
status=$?
rm _b.json
if [ $status -gt 0 ];
then
    exit $status
fi;
