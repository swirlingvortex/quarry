#include "bench.hpp"
#include "options.hpp"
#include <algorithm>
#include <bit>
#include <chrono>
#include <iostream>
#include <numeric>
#include <optional>
#include <random>
#include <set>
#include <sstream>
namespace quarry {
namespace {
using Clock=std::chrono::steady_clock;
std::uint64_t ns(Clock::time_point a,Clock::time_point b) {return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count());}
void fields(const json& object,std::initializer_list<std::string_view> allowed) {
    if(!object.is_object()) fail("CLI","benchmark entry must be an object");
    for(auto it=object.begin();it!=object.end();++it) if(std::find(allowed.begin(),allowed.end(),it.key())==allowed.end()) fail("CLI","unknown benchmark field: "+it.key());
}
std::size_t integer(const json& object,const char* name,std::size_t minimum,std::size_t maximum) {
    const auto& value=object.at(name);
    if(!value.is_number_unsigned() && !(value.is_number_integer() && value.get<std::int64_t>()>=0)) fail("CLI",std::string(name)+" must be an unsigned integer");
    auto n=value.get<std::size_t>();if(n<minimum || n>maximum) fail("CLI",std::string(name)+" outside benchmark bounds");return n;
}
std::filesystem::path relative(const std::filesystem::path& manifest,const json& value) {
    auto p=std::filesystem::path(value.get<std::string>());if(p.empty() || p.is_absolute()) fail("CLI","benchmark paths must be relative to manifest");return manifest.parent_path()/p;
}
json result_json(const Result& result) {
    json columns=json::array(),rows=json::array();
    for(const auto& column:result.columns) columns.push_back({{"name",column.name},{"type",type_name(column.type)}});
    for(const auto& row:result.rows) {
        json values=json::array();for(const auto& value:row) {
            if(value.is_null()) values.push_back(nullptr);
            else if(value.type==Type::Int64) values.push_back(std::to_string(value.integer()));
            else if(value.type==Type::Double) values.push_back(value.real());
            else if(value.type==Type::Bool) values.push_back(value.boolean());
            else values.push_back(std::string(value.string()));
        }
        rows.push_back(std::move(values));
    }
    return {{"ok",true},{"columns",std::move(columns)},{"rows",std::move(rows)}};
}
std::string digest(const Result& result) {
    std::uint64_t hash=14695981039346656037ULL;
    auto byte=[&](std::uint8_t b){hash^=b;hash*=1099511628211ULL;};
    auto number=[&](std::uint64_t n){for(int i=0;i<8;++i) {byte(static_cast<std::uint8_t>(n&255));n>>=8;}};
    auto string=[&](std::string_view s){number(s.size());for(unsigned char c:s) byte(c);};
    number(result.columns.size());for(const auto& column:result.columns) {string(column.name);number(static_cast<std::uint64_t>(column.type));}
    number(result.rows.size());for(const auto& row:result.rows) for(const auto& value:row) {
        byte(static_cast<std::uint8_t>(value.type));byte(static_cast<std::uint8_t>(value.is_null()));if(value.is_null()) continue;
        if(value.type==Type::Int64) number(static_cast<std::uint64_t>(value.integer()));
        else if(value.type==Type::Double) number(std::bit_cast<std::uint64_t>(value.real()));
        else if(value.type==Type::Bool) byte(static_cast<std::uint8_t>(value.boolean()));
        else string(value.string());
    }
    std::ostringstream out;out<<std::hex<<hash;return out.str();
}
struct Case {
    std::string id,workload,sql;ExecutionOptions options;PreparedQuery prepared;
    Case(std::string i,std::string w,std::string s,ExecutionOptions o,PreparedQuery p)
        :id(std::move(i)),workload(std::move(w)),sql(std::move(s)),options(o),prepared(std::move(p)) {}
};
}
int run_benchmark(const std::filesystem::path& path,bool validation) try {
    auto text=read_bounded(path,1024*1024);check_json_depth(text);json manifest;
    try {manifest=json::parse(text);} catch(const json::exception& error) {fail("CLI",std::string("invalid benchmark manifest: ")+error.what());}
    fields(manifest,{"version","catalog","seed","warmups","repetitions","memory_limit","result_limit","cases","metadata","tracks"});
    if(integer(manifest,"version",1,1)!=1) fail("CLI","unsupported benchmark version");
    auto seed=integer(manifest,"seed",0,SIZE_MAX),warmups=integer(manifest,"warmups",2,10),repetitions=integer(manifest,"repetitions",7,100);
    Options limits{integer(manifest,"memory_limit",1024,2ULL*1024*1024*1024),integer(manifest,"result_limit",1,1000000)};
    if(manifest.contains("metadata") && !manifest["metadata"].is_object()) fail("CLI","benchmark metadata must be an object");
    if(manifest.contains("tracks") && manifest["tracks"]!=json::array({"resident","prepared"})) fail("CLI","benchmark tracks must be resident and prepared");
    const auto& definitions=manifest.at("cases");if(!definitions.is_array() || definitions.empty() || definitions.size()>256) fail("CLI","benchmark requires 1..256 cases");
    Engine engine(limits);auto load_start=Clock::now();engine.load_catalog(relative(path,manifest.at("catalog")));auto load_done=Clock::now();
    std::vector<Case> cases;cases.reserve(definitions.size());std::set<std::string> ids;json preparation=json::object();
    for(const auto& definition:definitions) {
        fields(definition,{"id","workload","sql_file","options","order_keys"});
        auto id=definition.at("id").get<std::string>();
        if(id.empty() || id.size()>128 || !ids.insert(id).second) fail("CLI","empty, duplicate or oversized benchmark id");
        for(unsigned char ch:id) if(!((ch>='a'&&ch<='z') || (ch>='A'&&ch<='Z') || (ch>='0'&&ch<='9') || ch=='_' || ch=='-' || ch=='.')) fail("CLI","invalid benchmark id");
        if(!definition.at("order_keys").is_array()) fail("CLI","order_keys must be an array");
        for(const auto& key:definition.at("order_keys")) if(!key.is_number_unsigned() && !(key.is_number_integer() && key.get<std::int64_t>()>=0)) fail("CLI","order_keys require nonnegative integer positions");
        auto options=execution_options(definition.at("options"),{});if(options.profile) fail("CLI","benchmark profiling must be disabled");
        auto sql=read_bounded(relative(path,definition.at("sql_file")),65536);auto start=Clock::now();auto plan=engine.prepare(sql,options);auto done=Clock::now();
        preparation[id]=ns(start,done);cases.emplace_back(std::move(id),definition.at("workload").get<std::string>(),std::move(sql),options,std::move(plan));
    }
    json header={{"kind","header"},{"mode",validation ? "validation":"timing"},{"compiler",__VERSION__},{"build_type",QUARRY_BUILD_TYPE},
        {"ingestion_ns",ns(load_start,load_done)},{"seed",seed},{"warmups",warmups},{"repetitions",repetitions},{"case_count",cases.size()},{"preparation_ns",preparation},
        {"timing_scope","steady-clock wall nanoseconds; resident includes parse/bind/plan plus execution to common owning result sink; prepared creates fresh execution state; digest/render/record-output/destruction excluded from execution; rendering measured separately; profile=false; default counters retained"},
        {"memory_scope","engine-lifetime accounted peak includes catalog, all retained prepared plans and previous trials; current includes current result; JSON/runtime metadata excluded"},{"digest_algorithm","typed-order-sensitive-fnv1a64-v1; audit aid only, not correctness validation"}};
    std::cout<<header.dump()<<'\n'<<std::flush;
    if(validation) {
        for(const auto& item:cases) for(bool prepared:{false,true}) {
            std::optional<PreparedQuery> resident_plan;
            if(!prepared) resident_plan.emplace(engine.prepare(item.sql,item.options));
            auto result=engine.execute(prepared ? item.prepared:*resident_plan);
            std::cout<<json{{"kind","validation"},{"case_id",item.id},{"track",prepared ? "prepared":"resident"},{"result",result_json(result)}}.dump()<<'\n';
        }
        return 0;
    }
    std::vector<std::size_t> order(cases.size()*2);std::iota(order.begin(),order.end(),0);std::mt19937_64 random(seed);std::size_t sequence=0;
    for(std::size_t round=0;round<warmups+repetitions;++round) {
        // Explicit Fisher-Yates schedule is reproducible across standard libraries.
        for(std::size_t i=order.size();i>1;--i) std::swap(order[i-1],order[static_cast<std::size_t>(random()%i)]);
        for(auto job:order) {
            const auto& item=cases[job/2];bool prepared=job%2!=0;auto phase=round<warmups ? "warmup":"recorded";auto repeat=round<warmups ? round:round-warmups;
            try {
                std::optional<PreparedQuery> resident_plan;
                auto start=Clock::now();if(!prepared) resident_plan.emplace(engine.prepare(item.sql,item.options));auto ready=prepared ? start:Clock::now();
                auto result=engine.execute(prepared ? item.prepared:*resident_plan);auto done=Clock::now();
                auto typed_digest=digest(result);auto render_start=Clock::now();auto encoded=result_json(result).dump();auto render_done=Clock::now();
                json record={{"kind","measurement"},{"case_id",item.id},{"track",prepared ? "prepared":"resident"},{"phase",phase},{"repeat",repeat},{"order_index",sequence++},
                    {"planning_ns",prepared ? 0:ns(start,ready)},{"execution_ns",ns(ready,done)},{"resident_ns",ns(start,done)},
                    {"rendering_ns",ns(render_start,render_done)},{"output_rows",result.rows.size()},{"output_bytes",encoded.size()},{"digest",typed_digest},
                    {"peak_accounted_bytes",engine.memory()->peak()},{"current_accounted_bytes",engine.memory()->current()}};
                std::cout<<record.dump()<<'\n'<<std::flush;
            } catch(const Error& error) {
                std::cout<<json{{"kind","failure"},{"case_id",item.id},{"track",prepared ? "prepared":"resident"},{"phase",phase},{"repeat",repeat},{"order_index",sequence},
                    {"error",{{"code",error.code},{"message",error.what()}}}}.dump()<<'\n'<<std::flush;return 1;
            } catch(const std::bad_alloc&) {
                std::cout<<json{{"kind","failure"},{"case_id",item.id},{"track",prepared ? "prepared":"resident"},{"phase",phase},{"repeat",repeat},{"order_index",sequence},
                    {"error",{{"code","RESOURCE"},{"message","allocation failed"}}}}.dump()<<'\n'<<std::flush;return 1;
            }
        }
    }
    return 0;
}
catch(const json::exception& error) {fail("CLI",std::string("invalid benchmark manifest: ")+error.what());}
}
