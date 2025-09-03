
CREATE ROLE apireader LOGIN PASSWORD 'apireader' ;
CREATE ROLE nadeemlab LOGIN PASSWORD 'nadeemlab' ;
GRANT CONNECT ON DATABASE scstudies TO apireader;
GRANT USAGE ON SCHEMA public TO apireader;
GRANT CONNECT ON DATABASE scstudies TO nadeemlab;
GRANT USAGE ON SCHEMA public TO nadeemlab;
