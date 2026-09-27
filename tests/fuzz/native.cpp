#include "quarry/quarry.hpp"
#include <fstream>
#include <iostream>
#include <random>
#include <charconv>
#include <chrono>
#include <cstdlib>
using namespace quarry;
namespace {
void write(const std::filesystem::path& path,std::string_view bytes) {std::ofstream file(path,std::ios::binary);file.write(bytes.data(),static_cast<std::streamsize>(bytes.size()));if(!file) fail("IO","fuzz fixture write failed");}
struct Directory {std::filesystem::path path;bool keep=false;~Directory(){if(!keep) {std::error_code error;std::filesystem::remove_all(path,error);}}};
std::string mutate(std::string input,std::mt19937_64& random) {
    const std::string alphabet="SELECT from t i,d,b,s 0123456789+-*/=()<>!';,\n\r\t\\N\"";
    for(std::size_t n=0;n<1+random()%8;++n) {
        auto offset=random()%(input.size()+1);auto operation=random()%3;
        if(operation==0 && offset<input.size()) input.erase(offset,1);
        else if(operation==1 && offset<input.size()) input[offset]=static_cast<char>(random()%256);
        else input.insert(offset,1,alphabet[random()%alphabet.size()]);
    }
    return input;
}
}
int main() {
    constexpr std::uint64_t seed=1909202607;std::mt19937_64 random(seed);std::size_t count=512;
    if(auto env=std::getenv("QUARRY_FUZZ_CASES")) {std::string_view value(env);auto [end,error]=std::from_chars(value.data(),value.data()+value.size(),count);if(error!=std::errc{} || end!=value.data()+value.size() || count<1 || count>4096) return 2;}
    Directory dir{std::filesystem::path(QUARRY_FUZZ_ARTIFACT_DIR)/("quarry-fuzz-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()))};
    std::filesystem::create_directories(dir.path);
    write(dir.path/"catalog.json",R"({"tables":[{"name":"t","path":"t.csv","columns":[{"name":"i","type":"INT64","nullable":true},{"name":"d","type":"DOUBLE","nullable":true},{"name":"b","type":"BOOL","nullable":true},{"name":"s","type":"STRING","nullable":true}]}]})");
    const std::string csv="i,d,b,s\n1,1.25,true,alpha\n2,2.5,false,\"quoted, value\"\n\\N,\\N,\\N,\\N\n";
    write(dir.path/"t.csv",csv);Engine engine(Options{1024*1024,16});engine.load_catalog(dir.path/"catalog.json");auto baseline=engine.memory()->current();
    std::size_t sql_errors=0,csv_errors=0,index=0;std::string last_sql,last_csv,phase;
    try {
        for(std::size_t i=0;i<count;++i) {
            index=i;phase="sql";auto sql=mutate(i%2 ? "SELECT i,s FROM t WHERE b OR i IS NULL ORDER BY i LIMIT 2":"SELECT s,COUNT(*) AS n,SUM(i) AS total FROM t GROUP BY s ORDER BY s",random);
            last_sql=sql;ExecutionOptions options{i%2 ? ExecutionMode::Scalar:ExecutionMode::Vector,7};options.optimizer=i%3==0;
            try {auto result=engine.query(sql,options);if(result.rows.size()>16) fail("INTERNAL","fuzz result cap violated");}
            catch(const Error& error) {if(error.code=="INTERNAL") throw;++sql_errors;}
            if(engine.memory()->current()!=baseline) fail("INTERNAL","SQL fuzz allocation cleanup failed");
            phase="csv";auto bytes=mutate(csv,random);last_csv=bytes;write(dir.path/"t.csv",bytes);Engine candidate(Options{1024*1024,16});
            try {candidate.load_catalog(dir.path/"catalog.json");auto result=candidate.query("SELECT COUNT(*) AS n FROM t");(void)result;}
            catch(const Error& error) {if(error.code!="CSV" && error.code!="RESOURCE") throw;if(candidate.memory()->current()!=0) fail("INTERNAL","CSV fuzz partial publish or leaked allocation");++csv_errors;}
        }
        std::cout<<"{\"status\":\"PASS\",\"seed\":"<<seed<<",\"sql_mutations\":"<<count<<",\"csv_mutations\":"<<count<<",\"sql_rejections\":"<<sql_errors<<",\"csv_rejections\":"<<csv_errors<<",\"kind\":\"bounded deterministic mutation fuzzing\"}\n";
    } catch(const std::exception& error) {
        dir.keep=true;write(dir.path/"failing.sql",last_sql);write(dir.path/"mutated.csv",last_csv);write(dir.path/"baseline.csv",csv);
        write(dir.path/"failure.txt","seed="+std::to_string(seed)+" index="+std::to_string(index)+" phase="+phase+" error="+error.what()+"\n");
        std::cerr<<"Reproducer retained at "<<dir.path<<"\nFuzz failure seed="<<seed<<" error="<<error.what()<<"\n";return 1;}
}
