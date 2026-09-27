#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include "doctest.h"
#include "quarry/quarry.hpp"
#include "json.hpp"
#include <array>
#include <chrono>
#include <fstream>
#include <functional>
#include <limits>
#include <optional>
using namespace quarry;
using nlohmann::json;
namespace {
struct Fixture {
    std::filesystem::path directory;
    Fixture() {
        static unsigned serial = 0;
        directory = std::filesystem::current_path() / "unit-fixtures" / (std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + "-" + std::to_string(serial++));
        std::filesystem::create_directories(directory);
    }
    ~Fixture() { std::error_code error; std::filesystem::remove_all(directory, error); }
    void write(std::string file, std::string content) { std::ofstream out(directory / file, std::ios::binary); out << content; }
    void table(std::string csv, json columns = json::array({{{"name","i"},{"type","INT64"},{"nullable",true}},{{"name","d"},{"type","DOUBLE"},{"nullable",true}},{{"name","b"},{"type","BOOL"},{"nullable",true}},{{"name","s"},{"type","STRING"},{"nullable",true}}})) {
        write("t.csv",std::move(csv)); write("catalog.json",json{{"tables",json::array({{{"name","t"},{"path","t.csv"},{"columns",columns}}})}}.dump());
    }
    void load(Engine& engine) { engine.load_catalog(directory / "catalog.json"); }
};
void error_code(const std::function<void()>& action, const std::string& code) {
    try { action(); FAIL("expected quarry::Error"); }
    catch (const Error& e) { CHECK(e.code == code); }
}
std::string data() { return "i,d,b,s\n1,1.5,true,a\n2,2.5,false,b\n3,\\N,\\N,a\n\\N,4.5,true,\\N\n"; }
}
TEST_CASE("accounted allocations unwind on success and budget failure") {
    Memory memory(1024);
    { std::pmr::vector<int> v(&memory); v.resize(32); CHECK(memory.current() >= 128); CHECK_THROWS_AS(v.resize(1024), Error); CHECK(v.size() == 32); }
    CHECK(memory.current() == 0); CHECK(memory.peak() >= 128);
}
TEST_CASE("cross-resource Value assignment can report resource errors without terminating") {
    Memory a(4096), b(128);
    auto x = Value::string(std::string(64,'a'), &b);
    auto y = Value::string(std::string(1000,'b'), &a);
    CHECK_THROWS_AS(x = std::move(y), Error);
}
TEST_CASE("checked INT64 arithmetic boundaries and division") {
    CHECK(numeric("+", Value::integer(4), Value::integer(7)).integer() == 11);
    CHECK(numeric("/", Value::integer(5), Value::integer(2)).real() == 2.5);
    CHECK(numeric("-", Value::integer(INT64_MIN), Value::integer(INT64_MIN)).integer() == 0);
    for (auto op : {"+","*"}) error_code([&] { numeric(op,Value::integer(INT64_MAX),Value::integer(2)); },"NUMERIC");
    error_code([] { numeric("-",Value::integer(INT64_MIN),Value::integer(1)); },"NUMERIC");
    error_code([] { negate(Value::integer(INT64_MIN)); },"NUMERIC");
    error_code([] { numeric("/",Value::integer(1),Value::integer(0)); },"NUMERIC");
    CHECK(numeric("/",Value::null(Type::Int64),Value::integer(0)).is_null());
    error_code([] { numeric("*",Value::real(1e308),Value::real(1e308)); },"NUMERIC");
}
TEST_CASE("complete TRUE FALSE UNKNOWN truth tables") {
    std::array<Value,3> values = {Value::boolean(false),Value::boolean(true),Value::null(Type::Bool)};
    int ands[3][3] = {{0,0,0},{0,1,2},{0,2,2}};
    int ors[3][3] = {{0,1,2},{1,1,1},{2,1,2}};
    auto code = [](const Value& v) { return v.is_null() ? 2 : int(v.boolean()); };
    for (int a = 0; a < 3; ++a) for (int b = 0; b < 3; ++b) { CHECK(code(truth("and",values[a],values[b])) == ands[a][b]); CHECK(code(truth("or",values[a],values[b])) == ors[a][b]); }
    CHECK(code(truth("not",values[0])) == 1); CHECK(code(truth("not",values[1])) == 0); CHECK(code(truth("not",values[2])) == 2);
    CHECK(comparison("=",values[2],values[2]).is_null());
}
TEST_CASE("UTF-8 validation and unsigned byte comparison") {
    CHECK(valid_utf8("東京 café")); CHECK_FALSE(valid_utf8(std::string("\xc0\x80",2))); CHECK_FALSE(valid_utf8(std::string("\xed\xa0\x80",3))); CHECK_FALSE(valid_utf8(std::string("\xf4\x90\x80\x80",4)));
    Memory m(1024); CHECK(compare(Value::string("z",&m),Value::string("é",&m)) < 0);
}
TEST_CASE("strict typed CSV tokens and numeric bounds") {
    Memory m(4096);
    CHECK(parse_cell("-9223372036854775808",Type::Int64,&m).integer() == INT64_MIN);
    CHECK(parse_cell("+9223372036854775807",Type::Int64,&m).integer() == INT64_MAX);
    for (auto token : {"9223372036854775808","-9223372036854775809"," 1","1 ","+-1","++1","1.0",""}) error_code([&] { parse_cell(token,Type::Int64,&m); },"CSV");
    for (auto token : {"nan","inf","1e309"," 1.0","1.0 ","+-1.5","0x1p2","1e",""}) error_code([&] { parse_cell(token,Type::Double,&m); },"CSV");
    CHECK(parse_cell("-2.5e+2",Type::Double,&m).real() == -250.0);
    CHECK(parse_cell("TrUe",Type::Bool,&m).boolean());
    error_code([&] { parse_cell("1",Type::Bool,&m); },"CSV");
}
TEST_CASE("CSV null empty quotes CRLF commas embedded newlines and owned buffers") {
    Fixture f; f.table("i,d,b,s\r\n1,1.5,true,\r\n2,2.5,false,\"\\N\"\r\n3,3.5,TRUE,\"comma, quote\"\" and\nline\"\r\n\\N,\\N,\\N,\\N\r\n");
    Engine e; f.load(e); const auto& t = e.table("T"); REQUIRE(t.row_count == 4);
    CHECK(t.columns[3].at(0).string().empty()); CHECK(t.columns[3].at(1).string() == "\\N"); CHECK(t.columns[3].at(2).string() == "comma, quote\" and\nline"); CHECK(t.columns[3].at(3).is_null());
    f.write("t.csv","overwritten\n"); CHECK(t.columns[3].at(2).string() == "comma, quote\" and\nline");
}
TEST_CASE("empty one-row and 4099-row tables have correct bitmap boundaries") {
    Fixture f; Engine e;
    f.table("i,d,b,s\n"); f.load(e); CHECK(e.table("t").row_count == 0);
    f.table("i,d,b,s\n1,1.0,true,a"); f.load(e); CHECK(e.table("t").row_count == 1);
    std::string csv = "i,d,b,s\n";
    for (int i = 0; i < 4099; ++i) csv += std::to_string(i) + ",1.0,true," + (i % 2 ? "\\N" : "x") + "\n";
    f.table(csv); f.load(e); CHECK(e.table("t").row_count == 4099);
    for (std::size_t i = 0; i < 4099; ++i) CHECK(e.table("t").columns[3].at(i).is_null() == bool(i % 2));
}
TEST_CASE("CSV malformed records return location diagnostics and leave no partial table") {
    Fixture f;
    for (auto csv : {"", "wrong,d,b,s\n", "i,d,b,s\n1,1.0,true\n", "i,d,b,s\n1,1.0,true,x,y\n", "i,d,b,s\n1,1.0,true,\"unclosed", "i,d,b,s\n1,1.0,true,\"x\"q\n", "i,d,b,s\n1,1.0,true,a\"b\n", "i,d,b,s\n1,1.0,true,x\r"}) {
        f.table(csv); Engine e;
        try { f.load(e); FAIL("invalid CSV accepted"); } catch (const Error& err) { CHECK(err.code == "CSV"); CHECK(std::string(err.what()).find("record") != std::string::npos); CHECK(std::string(err.what()).find("column") != std::string::npos); }
        CHECK(e.memory()->current() == 0); error_code([&] { (void)e.table("t"); },"BIND");
    }
}
TEST_CASE("failed reload preserves original catalog and memory baseline") {
    Fixture f; f.table(data()); Engine e; f.load(e); auto baseline = e.memory()->current();
    f.table("i,d,b,s\n1,1.0,true,x\n9223372036854775808,2.0,false,y\n");
    error_code([&] { f.load(e); },"CSV"); CHECK(e.memory()->current() == baseline); CHECK(e.table("t").row_count == 4);
}
TEST_CASE("invalid UTF-8 nonnullable NULL duplicate columns and field caps") {
    Fixture f; Engine e;
    f.table("i,d,b,s\n1,1.0,true," + std::string("\xff",1) + "\n"); error_code([&] { f.load(e); },"CSV");
    f.table("i\n\\N\n",json::array({{{"name","i"},{"type","INT64"},{"nullable",false}}})); error_code([&] { f.load(e); },"CSV");
    auto column = json{{"name","i"},{"type","INT64"},{"nullable",true}};
    f.table("i,i\n",json::array({column,column})); error_code([&] { f.load(e); },"CATALOG");
    f.table("i,d,b,s\n1,1.0,true," + std::string(1024*1024+1,'x') + "\n"); error_code([&] { f.load(e); },"CSV"); CHECK(e.memory()->current() == 0);
}
TEST_CASE("query precedence qualification aliases and lossless minimum integer") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    auto r = e.query("-- leading comment\nSELECT x.i AS n, 2+3*4 AS a, (2+3)*4 AS c, -9223372036854775808 AS lo FROM T AS x WHERE NOT i = 2 AND i <= 3 ORDER BY n;");
    REQUIRE(r.rows.size() == 2); CHECK(r.rows[0][0].integer() == 1); CHECK(r.rows[1][0].integer() == 3); CHECK(r.rows[0][1].integer() == 14); CHECK(r.rows[0][2].integer() == 20); CHECK(r.rows[0][3].integer() == INT64_MIN);
}
TEST_CASE("binding rejects missing names mixed types ambiguous order grouping and functions") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    for (auto sql : {"SELECT nope FROM t","SELECT t.i FROM t AS x","SELECT i AS x,d AS x FROM t ORDER BY x","SELECT i FROM t GROUP BY b","SELECT COUNT(SUM(i)) FROM t","SELECT i FROM t ORDER BY 2"}) error_code([&] { e.query(sql); },"BIND");
    for (auto sql : {"SELECT i+d FROM t","SELECT i FROM t WHERE i = 1.0","SELECT NULL FROM t","SELECT SUM(NULL) FROM t","SELECT SUM(s) FROM t","SELECT d FROM t GROUP BY d","SELECT CAST(i AS VARCHAR) FROM t"}) error_code([&] { e.query(sql); },"TYPE");
    for (auto sql : {"SELECT DISTINCT i FROM t","SELECT i FROM t WHERE i+1=2","SELECT i FROM t WHERE CAST(i AS DOUBLE)=1.0","SELECT abs(i) FROM t","SELECT i FROM t LIMIT 1 OFFSET 1","SELECT i FROM t; SELECT i FROM t","SELECT i FROM t INNER JOIN t AS x ON i=x.i"}) CHECK_THROWS_AS(e.query(sql),Error);
}
TEST_CASE("null contextual typing casts and empty predicate behavior") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    auto r = e.query("SELECT NULL+1 AS a, NULL=NULL AS b, CAST(NULL AS VARCHAR) AS c, CAST(i AS DOUBLE) AS d, b OR NULL AS e FROM t ORDER BY d");
    REQUIRE(r.rows.size() == 4); CHECK(r.columns[0].type == Type::Int64); CHECK(r.columns[1].type == Type::Bool); CHECK(r.columns[2].type == Type::String); CHECK(r.rows[0][0].is_null()); CHECK(r.rows[0][1].is_null()); CHECK(r.rows[0][4].boolean()); CHECK(r.rows[1][4].is_null());
    CHECK(e.query("SELECT * FROM t WHERE NULL").rows.empty());
}
TEST_CASE("filter masks projection failures but LIMIT does not change evaluation domain") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    CHECK(e.query("SELECT 1/0 AS bad FROM t WHERE FALSE LIMIT 0").rows.empty());
    error_code([&] { e.query("SELECT 1/(i-2) AS bad FROM t LIMIT 1"); },"NUMERIC");
    error_code([&] { e.query("SELECT 1/0 AS bad FROM t LIMIT 0"); },"NUMERIC");
    CHECK(e.query("SELECT 1/(i-2) AS x FROM t WHERE i <> 2").rows.size() == 2);
}
TEST_CASE("global grouped composite and nullable aggregation hand computations") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    auto r = e.query("SELECT COUNT(*) AS n, COUNT(i) AS nn, SUM(i) AS s, AVG(i) AS a, MIN(s) AS lo, MAX(b) AS yes FROM t");
    REQUIRE(r.rows.size() == 1); CHECK(r.rows[0][0].integer() == 4); CHECK(r.rows[0][1].integer() == 3); CHECK(r.rows[0][2].integer() == 6); CHECK(r.rows[0][3].real() == 2); CHECK(r.rows[0][4].string() == "a"); CHECK(r.rows[0][5].boolean());
    auto g = e.query("SELECT s, b, COUNT(*) AS n, SUM(i)+10 AS total FROM t GROUP BY s,b ORDER BY s,b NULLS FIRST"); REQUIRE(g.rows.size() == 4);
    auto grouped = e.query("SELECT s,COUNT(*) AS n,SUM(i) AS total FROM t GROUP BY s ORDER BY s"); REQUIRE(grouped.rows.size() == 3); CHECK(grouped.rows[0][1].integer() == 2); CHECK(grouped.rows[0][2].integer() == 4); CHECK(grouped.rows[2][0].is_null());
    CHECK(e.query("SELECT i*2 AS v FROM t GROUP BY i").rows.size() == 4);
}
TEST_CASE("empty global aggregates return one row while grouped input returns none") {
    Fixture f; f.table("i,d,b,s\n"); Engine e; f.load(e);
    auto r = e.query("SELECT COUNT(*) AS n,COUNT(i) AS c,SUM(i) AS s,AVG(d) AS a,MIN(b) AS lo,MAX(s) AS hi FROM t"); REQUIRE(r.rows.size() == 1); CHECK(r.rows[0][0].integer() == 0); CHECK(r.rows[0][1].integer() == 0); for (std::size_t c=2;c<6;++c) CHECK(r.rows[0][c].is_null());
    CHECK(e.query("SELECT s,COUNT(*) AS n FROM t GROUP BY s").rows.empty());
}
TEST_CASE("wide integer SUM cancellation final overflow and AVG independent of SUM range") {
    Fixture f; f.table("i,d,b,s\n9223372036854775807,1.0,true,a\n9223372036854775807,1.0,true,a\n-9223372036854775807,1.0,true,a\n"); Engine e; f.load(e);
    CHECK(e.query("SELECT SUM(i) AS s FROM t").rows[0][0].integer() == INT64_MAX);
    error_code([&] { e.query("SELECT SUM(i) AS s FROM t WHERE i > 0"); },"NUMERIC");
    CHECK(e.query("SELECT AVG(i) AS a FROM t WHERE i > 0").rows[0][0].real() == static_cast<double>(INT64_MAX));
}
TEST_CASE("DOUBLE aggregate order cancellation and nonfinite intermediate errors") {
    Fixture f; f.table("i,d,b,s\n1,10000000000000000.0,true,a\n2,1.0,true,a\n3,-10000000000000000.0,true,a\n"); Engine e; f.load(e);
    CHECK(e.query("SELECT SUM(d) AS s FROM t").rows[0][0].real() == 0.0);
    f.table("i,d,b,s\n1,1e308,true,a\n2,1e308,true,a\n3,-1e308,true,a\n"); f.load(e);
    error_code([&] { e.query("SELECT SUM(d) AS s FROM t"); },"NUMERIC"); error_code([&] { e.query("SELECT AVG(d) AS a FROM t"); },"NUMERIC");
}
TEST_CASE("sorting uses output names positions defaults null placement and preserves duplicates") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    auto descending = e.query("SELECT i FROM t ORDER BY 1 DESC LIMIT 4"); REQUIRE(descending.rows.size() == 4); CHECK(descending.rows[0][0].integer() == 3); CHECK(descending.rows[3][0].is_null());
    auto first = e.query("SELECT i AS n FROM t ORDER BY n DESC NULLS FIRST LIMIT 2"); CHECK(first.rows[0][0].is_null()); CHECK(first.rows[1][0].integer() == 3);
    auto duplicates = e.query("SELECT s FROM t WHERE s = 'a'"); CHECK(duplicates.rows.size() == 2);
}
TEST_CASE("result and group caps fail without leaking and preserve later queries") {
    Fixture f; f.table(data()); Engine e(Options{1024*1024,2}); f.load(e); auto baseline = e.memory()->current();
    error_code([&] { e.query("SELECT * FROM t LIMIT 1"); },"RESOURCE"); CHECK(e.memory()->current() == baseline);
    error_code([&] { e.query("SELECT s FROM t GROUP BY s LIMIT 1"); },"RESOURCE"); CHECK(e.memory()->current() == baseline);
    { auto r = e.query("SELECT COUNT(*) AS n FROM t"); CHECK(r.rows[0][0].integer() == 4); }
    CHECK(e.memory()->current() == baseline);
}
TEST_CASE("query memory error releases strings hash state and result storage") {
    Fixture f; f.table("i,d,b,s\n1,1.0,true,"+std::string(2048,'x')+"\n2,2.0,false,"+std::string(2048,'y')+"\n"); Engine e(Options{14000,100}); f.load(e); auto baseline=e.memory()->current();
    error_code([&] { e.query("SELECT s,s,s,s,s,s,s,s FROM t"); },"RESOURCE"); CHECK(e.memory()->current() == baseline);
    { auto r=e.query("SELECT COUNT(*) AS n FROM t"); CHECK(r.rows[0][0].integer()==2); }
    CHECK(e.memory()->current()==baseline);
}
TEST_CASE("result strings outlive engine and query AST owners") {
    Fixture f; f.table(data()); std::optional<Result> result;
    { Engine e; f.load(e); result.emplace(e.query("SELECT s, 'a long literal that requires an allocation' AS x FROM t")); }
    CHECK(result->rows[0][0].string() == "a"); CHECK(result->rows[0][1].string() == "a long literal that requires an allocation");
    auto owner = result->memory; result.reset(); CHECK(owner->current() == 0);
}
TEST_CASE("SQL nesting length and token caps protect parser and binder") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    error_code([&] { e.query("SELECT " + std::string(150,'(') + "1" + std::string(150,')') + " FROM t"); },"RESOURCE");
    std::string chain = "SELECT 1"; for (int i=0;i<150;++i) chain += "+1"; chain += " FROM t"; error_code([&] { e.query(chain); },"RESOURCE");
    error_code([&] { e.query(std::string(65537,' ')); },"RESOURCE");
}
TEST_CASE("explain contains bound scalar stages and identical optimizer-off semantics") {
    Fixture f; f.table(data()); Engine e; f.load(e);
    auto p=e.explain("SELECT s,SUM(i) AS n FROM t WHERE b GROUP BY s ORDER BY n LIMIT 1"); REQUIRE(p.logical.size()==6); CHECK(p.logical[0].kind=="Scan"); CHECK(p.logical[2].kind=="HashAggregate"); CHECK(p.physical[2].kind=="ScalarHashAggregate"); CHECK(p.logical.back().output[1].type==Type::Int64);
}
TEST_CASE("vector result and aggregate string views become owning sink values") {
    Fixture f; std::string csv="i,d,b,s\n";
    for(int i=0;i<40;++i) csv+=std::to_string(i)+",1.0,true,"+std::string(300,char('a'+i%20))+"\n";
    f.table(csv); std::optional<Result> result;
    { Engine e; f.load(e);result.emplace(e.query("SELECT s,MIN(s) AS lo,COUNT(*) AS n FROM t GROUP BY s ORDER BY s",ExecutionOptions{ExecutionMode::Vector,7})); }
    REQUIRE(result->rows.size()==20);CHECK(std::string_view(result->rows[0][0].string())==std::string(300,'a'));CHECK(std::string_view(result->rows[0][1].string())==std::string(300,'a'));CHECK(result->rows[19][2].integer()==2);
    auto memory=result->memory;result.reset();CHECK(memory->current()==0);
}
TEST_CASE("vector uses real input batches and survives empty selections and partial tails") {
    Fixture f;std::string csv="i,d,b,s\n";for(int i=0;i<4103;++i) csv+=std::to_string(i)+",1.0,true,x\n";f.table(csv);Engine e;f.load(e);
    for(auto size:{1,7,256,1024,4096}) {
        auto r=e.query("SELECT i+1 AS n FROM t WHERE i >= 4096 ORDER BY n DESC LIMIT 2",ExecutionOptions{ExecutionMode::Vector,std::size_t(size)});
        REQUIRE(r.rows.size()==2);CHECK(r.rows[0][0].integer()==4103);CHECK(r.input_batches==(4103+std::size_t(size)-1)/std::size_t(size));CHECK(r.scanned_rows==4103);CHECK(r.filtered_rows==7);
    }
}
TEST_CASE("vector failure returns accounted buffers and leaves engine reusable") {
    Fixture f;f.table(data());Engine e;f.load(e);auto baseline=e.memory()->current();
    for(auto size:{1,7,256,1024,4096}) {
        auto opts=ExecutionOptions{ExecutionMode::Vector,std::size_t(size)};
        error_code([&]{e.query("SELECT 1/(i-2) AS bad FROM t LIMIT 0",opts);},"NUMERIC");CHECK(e.memory()->current()==baseline);
        {auto r=e.query("SELECT COUNT(*) AS n,COUNT(NULL) AS z FROM t",opts);CHECK(r.rows[0][0].integer()==4);CHECK(r.rows[0][1].integer()==0);}
        CHECK(e.memory()->current()==baseline);
    }
}
TEST_CASE("vector floating aggregation preserves exact scalar accumulation order across batches") {
    Fixture f;std::string csv="i,d,b,s\n";for(int i=0;i<4101;++i) csv+=std::to_string(i)+","+(i%3==0?"1e16":i%3==1?"1.0":"-1e16")+",true,x\n";f.table(csv);Engine e;f.load(e);
    const auto sql="SELECT SUM(d) AS s, AVG(d) AS a FROM t";auto scalar=e.query(sql);
    for(auto size:{1,7,256,1024,4096}) {auto r=e.query(sql,ExecutionOptions{ExecutionMode::Vector,std::size_t(size)});CHECK(r.rows[0][0].real()==scalar.rows[0][0].real());CHECK(r.rows[0][1].real()==scalar.rows[0][1].real());}
}
namespace {
void joined_fixture(Fixture& f) {
    f.table("i,d,b,s\n1,1.0,true,"+std::string(300,'a')+"\n1,2.0,true,"+std::string(300,'b')+"\n\\N,3.0,true,missing\n");
    auto catalog=json::parse(read_bounded(f.directory/"catalog.json",65536));auto right=catalog["tables"][0];right["name"]="u";right["path"]="u.csv";catalog["tables"].push_back(right);f.write("catalog.json",catalog.dump());
    f.write("u.csv","i,d,b,s\n1,4.0,true,"+std::string(300,'x')+"\n1,5.0,true,"+std::string(300,'y')+"\n1,6.0,false,z\n\\N,7.0,true,missing\n");
}
}
TEST_CASE("hash joins preserve composite null and duplicate semantics in both traversals and build sides") {
    Fixture f;joined_fixture(f);Engine e;f.load(e);auto baseline=e.memory()->current();
    for(auto mode:{ExecutionMode::Scalar,ExecutionMode::Vector}) for(auto side:{BuildSide::Left,BuildSide::Right}) {
        auto opts=ExecutionOptions{mode,1,side};
        {auto r=e.query("SELECT l.s AS a,r.s AS b FROM t AS l INNER JOIN u AS r ON l.i=r.i AND l.b=r.b ORDER BY a,b",opts);REQUIRE(r.rows.size()==4);CHECK(r.rows[0][0].string().size()==300);CHECK(r.rows[3][1].string().size()==300);}
        CHECK(e.memory()->current()==baseline);
        {auto r=e.query("SELECT COUNT(*) AS n FROM t AS l INNER JOIN u AS r ON l.i=r.i",opts);CHECK(r.rows[0][0].integer()==6);}
        CHECK(e.memory()->current()==baseline);
    }
}
TEST_CASE("joined vector aggregate result owns strings after catalog cursor and groups die") {
    Fixture f;joined_fixture(f);std::optional<Result> result;
    {Engine e;f.load(e);result.emplace(e.query("SELECT l.s,MIN(r.s) AS lo FROM t AS l INNER JOIN u AS r ON l.i=r.i AND l.b=r.b GROUP BY l.s ORDER BY 1",ExecutionOptions{ExecutionMode::Vector,1}));}
    REQUIRE(result->rows.size()==2);CHECK(std::string_view(result->rows[0][1].string())==std::string(300,'x'));auto memory=result->memory;result.reset();CHECK(memory->current()==0);
}
TEST_CASE("join failures unwind hash allocations and do not corrupt subsequent queries") {
    Fixture f;joined_fixture(f);Engine e(Options{1024*1024,2});f.load(e);auto baseline=e.memory()->current();
    for(auto mode:{ExecutionMode::Scalar,ExecutionMode::Vector}) {
        auto opts=ExecutionOptions{mode,7};
        error_code([&]{e.query("SELECT l.s,r.s FROM t AS l INNER JOIN u AS r ON l.i=r.i LIMIT 1",opts);},"RESOURCE");CHECK(e.memory()->current()==baseline);
        {auto r=e.query("SELECT COUNT(*) AS n FROM t AS l INNER JOIN u AS r ON l.i=r.i",opts);CHECK(r.rows[0][0].integer()==6);}
        CHECK(e.memory()->current()==baseline);
        opts.build_side=BuildSide::Left;
        error_code([&]{e.query("SELECT SUM(l.d) AS n FROM t AS l INNER JOIN u AS r ON l.i=r.i",opts);},"UNSUPPORTED");CHECK(e.memory()->current()==baseline);
    }
}
TEST_CASE("optimizer compact scans retain hidden join group and predicate columns with owning results") {
    Fixture f;joined_fixture(f);
    for(auto mode:{ExecutionMode::Scalar,ExecutionMode::Vector}) {
        std::optional<Result> result;
        {Engine e;f.load(e);ExecutionOptions opts{mode,1};opts.optimizer=true;opts.profile=true;
            result.emplace(e.query("SELECT MIN(r.s) AS lo,COUNT(*) AS n,(2+3)*4 AS folded FROM t AS l INNER JOIN u AS r ON l.i=r.i WHERE l.b AND r.b GROUP BY l.s ORDER BY lo",opts));
            CHECK(result->plan.applications.column_pruning==2);CHECK(result->plan.applications.predicate_pushdown==2);
            CHECK(result->plan.applications.constant_folding==2);CHECK(result->plan.build_side=="left");
            std::size_t opened=0,read=0;for(const auto& stats:result->operators) {opened+=stats.columns_opened;read+=stats.columns_read;}
            CHECK(opened==6);CHECK(read==6);
        }
        REQUIRE(result->rows.size()==2);CHECK(std::string_view(result->rows[0][0].string())==std::string(300,'x'));
        CHECK(result->rows[0][1].integer()==2);CHECK(result->rows[0][2].integer()==20);
        auto owner=result->memory;result.reset();CHECK(owner->current()==0);
    }
}
TEST_CASE("optimized failures unwind compact descriptors streams and join storage before reuse") {
    Fixture f;joined_fixture(f);Engine e(Options{1024*1024,2});f.load(e);auto baseline=e.memory()->current();
    for(auto mode:{ExecutionMode::Scalar,ExecutionMode::Vector}) for(auto size:{1,7,4096}) {
        ExecutionOptions opts{mode,std::size_t(size)};opts.optimizer=true;
        error_code([&]{e.query("SELECT l.s,r.s FROM t AS l INNER JOIN u AS r ON l.i=r.i WHERE l.b",opts);},"RESOURCE");CHECK(e.memory()->current()==baseline);
        error_code([&]{e.query("SELECT 1/0 AS bad FROM t AS l INNER JOIN u AS r ON l.i=r.i WHERE l.b",opts);},"NUMERIC");CHECK(e.memory()->current()==baseline);
        {auto r=e.query("SELECT COUNT(*) AS n FROM t AS l INNER JOIN u AS r ON l.i=r.i WHERE l.b AND r.b",opts);CHECK(r.rows[0][0].integer()==4);}
        CHECK(e.memory()->current()==baseline);
        {auto r=e.query("SELECT (NULL AND FALSE) AS x,(NULL OR TRUE) AS y FROM t WHERE i IS NULL",opts);REQUIRE(r.rows.size()==1);CHECK(!r.rows[0][0].boolean());CHECK(r.rows[0][1].boolean());}
        CHECK(e.memory()->current()==baseline);
    }
}
TEST_CASE("prepared execution resets operator state and counters and retains independent results") {
    Fixture f;joined_fixture(f);Engine e;f.load(e);
    for(auto mode:{ExecutionMode::Scalar,ExecutionMode::Vector}) {
        ExecutionOptions options{mode,7};options.optimizer=true;
        auto prepared=e.prepare("SELECT l.s,MIN(r.s) AS lo,COUNT(*) AS n FROM t AS l INNER JOIN u AS r ON l.i=r.i WHERE r.b GROUP BY l.s ORDER BY 1",options);
        auto baseline=e.memory()->current();std::size_t reads=0;
        for(int repeat=0;repeat<3;++repeat) {
            {auto result=e.execute(prepared);REQUIRE(result.rows.size()==2);CHECK(result.rows[0][2].integer()==2);
                std::size_t current_reads=0;for(const auto& stats:result.operators) current_reads+=stats.values_read;
                if(repeat==0) reads=current_reads;else CHECK(current_reads==reads);}
            CHECK(e.memory()->current()==baseline);
        }
        auto retained=e.execute(prepared);auto another=e.execute(prepared);CHECK(retained.rows[0][0].string()==another.rows[0][0].string());
    }
}
TEST_CASE("prepared catalog identity rejects replacement foreign engine and moved plans") {
    Fixture f;f.table(data());Engine e;f.load(e);Engine other;f.load(other);
    auto prepared=e.prepare("SELECT i FROM t");error_code([&]{other.execute(prepared);},"BIND");
    f.table("i,d,b,s\nwrong,1.0,true,x\n");error_code([&]{f.load(e);},"CSV");CHECK(e.execute(prepared).rows.size()==4);
    auto moved=std::move(prepared);error_code([&]{e.execute(prepared);},"BIND");CHECK(e.execute(moved).rows.size()==4);
    f.table(data());f.load(e);error_code([&]{e.execute(moved);},"BIND");
}
TEST_CASE("prepared AST resource remains alive after engine destruction and move assignment") {
    Fixture f;f.table(data());std::optional<PreparedQuery> prepared;std::shared_ptr<Memory> owner;
    {Engine e;f.load(e);owner=e.memory();prepared.emplace(e.prepare("SELECT 'long owned literal requiring heap allocation' AS s FROM t"));}
    CHECK(owner->current()>0);prepared.reset();CHECK(owner->current()==0);
    Engine e;f.load(e);auto a=e.prepare("SELECT 'first long owned literal requiring heap allocation' AS s FROM t");
    auto b=e.prepare("SELECT 'second long owned literal requiring heap allocation' AS s FROM t");a=std::move(b);
    CHECK(e.execute(a).rows[0][0].string()=="second long owned literal requiring heap allocation");
}
TEST_CASE("injected accounted allocation failures unwind every query allocation prefix") {
    Fixture f;joined_fixture(f);Engine e;f.load(e);
    for(auto mode:{ExecutionMode::Scalar,ExecutionMode::Vector}) {
        ExecutionOptions options{mode,7};options.optimizer=true;
        auto prepared=e.prepare("SELECT l.s,MIN(r.s) AS lo,COUNT(*) AS n FROM t AS l INNER JOIN u AS r ON l.i=r.i WHERE r.b GROUP BY l.s ORDER BY 1",options);
        auto baseline=e.memory()->current();bool completed=false;std::size_t failures=0;
        for(std::size_t allowed=0;allowed<512;++allowed) {
            e.memory()->set_failure_after(allowed);
            try {auto result=e.execute(prepared);CHECK(result.rows.size()==2);completed=true;}
            catch(const Error& error) {CHECK(error.code=="RESOURCE");CHECK(std::string(error.what()).find("injected")!=std::string::npos);++failures;}
            e.memory()->set_failure_after(std::nullopt);CHECK(e.memory()->current()==baseline);
            {auto recovered=e.execute(prepared);CHECK(recovered.rows.size()==2);}CHECK(e.memory()->current()==baseline);
            if(completed) break;
        }
        CHECK(completed);CHECK(failures>20);
    }
}
TEST_CASE("injected loading failures publish no partial catalog and preserve prepared queries") {
    Fixture f;joined_fixture(f);Engine e;f.load(e);auto original=e.prepare("SELECT COUNT(*) AS n FROM t");
    auto baseline=e.memory()->current();bool completed=false;std::size_t failures=0;
    for(std::size_t allowed=0;allowed<512;++allowed) {
        e.memory()->set_failure_after(allowed);
        try {f.load(e);completed=true;}
        catch(const Error& error) {CHECK(error.code=="RESOURCE");++failures;}
        e.memory()->set_failure_after(std::nullopt);CHECK(e.memory()->current()==baseline);
        if(completed) {error_code([&]{e.execute(original);},"BIND");break;}
        {auto result=e.execute(original);CHECK(result.rows[0][0].integer()==3);}CHECK(e.memory()->current()==baseline);
    }
    CHECK(completed);CHECK(failures>10);
}
