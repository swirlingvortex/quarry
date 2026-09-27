#include "quarry/quarry.hpp"
#include "json.hpp"
#include "options.hpp"
#include "bench.hpp"
#include <charconv>
#include <iostream>
#include <optional>
#include <sstream>
#include <unordered_map>
#include <unordered_set>
#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif
#if defined(__APPLE__) || defined(__linux__)
#include <sys/resource.h>
#endif

using nlohmann::json;
using namespace quarry;
namespace {
const char* help = R"(Quarry M6 — scalar and typed batch analytical SQL
Usage:
  quarry query --catalog PATH (--sql SQL | --sql-file PATH) [options]
  quarry explain --catalog PATH (--sql SQL | --sql-file PATH)
  quarry session --stdio --catalog PATH [resource options]
  quarry demo
  quarry bench --manifest PATH [--validate-only]
Options:
  --engine scalar|vector  Execution path (default scalar)
  --batch-size N          Vector batch size 1..65536 (default 1024)
  --optimizer on|off      Conservative rules (default off)
  --prune on|off          Column descriptor pruning
  --pushdown on|off       Total single-source predicates below inner joins
  --fold on|off           Successful literal constant folding
  --join-reorder on|off   Safe smaller-input join build selection
  --profile              Include scoped operator timing
  --analyze              Execute EXPLAIN and include result/profile
  --build-side auto|left|right  Join physical test control
  --format table|json     Query output, default table
  --memory-limit BYTES    Accounted memory budget, default 536870912
  --result-limit ROWS     Materialized result/group cap, default 100000
  --help                  Show this help
JSON INT64 cells are decimal strings. One inner equijoin is supported. Bench emits native JSONL records.
)";
json error_json(std::string code, std::string message) { return {{"ok",false},{"error",{{"code",std::move(code)},{"message",std::move(message)}}}}; }
json columns_json(const std::vector<OutputColumn>& columns) {
    auto out = json::array(); for (const auto& c : columns) out.push_back({{"name",c.name},{"type",type_name(c.type)}}); return out;
}
json value_json(const Value& value) {
    if (value.is_null()) return nullptr;
    if (value.type == Type::Int64) return std::to_string(value.integer());
    if (value.type == Type::Double) return value.real();
    if (value.type == Type::Bool) return value.boolean();
    return std::string(value.string());
}
json rules_json(const RuleApplications& counts) {
    return {{"column_pruning",counts.column_pruning},{"predicate_pushdown",counts.predicate_pushdown},{"constant_folding",counts.constant_folding},{"join_build_side",counts.join_build_side}};
}
json join_json(const Plan& plan) {return {{"build_side",plan.build_side},{"reason",plan.join_reason}};}
json result_json(const Result& result) {
    json rows = json::array();
    for (const auto& row : result.rows) { json values = json::array(); for (const auto& value : row) values.push_back(value_json(value)); rows.push_back(std::move(values)); }
    json output = {{"ok",true},{"columns",columns_json(result.columns)},{"rows",std::move(rows)},
            {"stats",{{"peak_accounted_bytes",result.memory->peak()},{"current_accounted_bytes",result.memory->current()},{"scanned_rows",result.scanned_rows},{"filtered_rows",result.filtered_rows},{"input_batches",result.input_batches}}}};
    auto& stats=output["stats"];stats["operators"]=json::array();
    stats["rule_applications"]=rules_json(result.plan.applications);stats["join"]=join_json(result.plan);
    stats["engine"]=result.plan.engine==ExecutionMode::Scalar ? "scalar":"vector";stats["batch_size"]=result.plan.options.batch_size;
    stats["accounting_scope"]="requested PMR bytes allocated within inclusive operator scopes; nested scopes overlap; metadata and JSON excluded";
    for(const auto& op:result.operators) {
        json item={{"id",op.id},{"operator",op.kind},{"source",op.source},{"input_rows",op.input_rows},{"output_rows",op.output_rows},{"batches",op.batches},
            {"columns_opened",op.columns_opened},{"columns_read",op.columns_read},{"values_read",op.values_read},{"build_rows",op.build_rows},{"probe_rows",op.probe_rows},
            {"candidate_rows",op.candidate_rows},{"accounted_allocation_bytes",op.accounted_allocation_bytes}};
        if(result.plan.options.profile) {item["elapsed_ns"]=op.elapsed_ns;item["timing_scope"]="inclusive active operator work; parent/child scopes overlap; scan covers descriptors/row traversal, payload reads occur in consumers";}
        stats["operators"].push_back(std::move(item));
    }
    if(result.plan.options.profile) stats["timings"]={{"planning_ns",result.planning_ns},{"execution_ns",result.execution_ns},{"scope","steady-clock wall time; planning includes parse/bind/optimize; execution includes sink and operator setup/teardown; excludes catalog and JSON; do not sum inclusive operators"}};
#if defined(__APPLE__) || defined(__linux__)
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) == 0) {
        std::uint64_t bytes = static_cast<std::uint64_t>(usage.ru_maxrss);
#if defined(__linux__)
        bytes *= 1024;
#endif
        output["stats"]["process_peak_rss_bytes"] = bytes;
        output["stats"]["rss_scope"] = "process lifetime high-water mark through result JSON construction";
    }
#endif
    return output;
}
json plan_json(const Plan& plan) {
    auto stages = [&](const std::vector<PlanStage>& source) {
        json out = json::array(); for (const auto& stage : source) out.push_back({{"id",stage.id},{"operator",stage.kind},{"engine",plan.engine==ExecutionMode::Scalar ? "scalar" : "vector"},{"columns",columns_json(stage.output)},{"source",stage.source},{"bound_columns",stage.bound_columns},{"inputs",stage.inputs},{"predicates",stage.predicates}}); return out;
    };
    auto logical = stages(plan.logical);
    return {{"ok",true},{"optimizer",plan.options.optimizer ? "on":"off"},{"unoptimized_logical",logical},{"optimized_logical",stages(plan.optimized)},
        {"physical",stages(plan.physical)},{"join",join_json(plan)},{"rule_applications",rules_json(plan.applications)},
        {"rules",{{"prune",plan.options.optimizer && plan.options.prune},{"pushdown",plan.options.optimizer && plan.options.pushdown},{"fold",plan.options.optimizer && plan.options.fold},{"build_side",plan.options.optimizer && plan.options.join_reorder}}}};
}
std::size_t size_arg(const std::string& text) {
    std::size_t n;
    auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), n);
    if (ec != std::errc() || end != text.data() + text.size()) fail("CLI", "invalid nonnegative integer: " + text);
    return n;
}
bool request_line(std::string& line, bool& oversized) {
    line.clear(); oversized = false; bool any = false;
    char c;
    while (std::cin.get(c)) {
        any = true; if (c == '\n') return true;
        if (line.size() < 131072) line += c; else oversized = true;
    }
    return any;
}
void session(const Engine& engine,ExecutionOptions defaults) {
    std::string line; bool oversized;
    while (request_line(line, oversized)) {
        json response, id; bool has_id = false;
        try {
            if (oversized) fail("RESOURCE", "session request exceeds 128 KiB");
            check_json_depth(line);
            auto request = json::parse(line);
            if (request.is_object() && request.contains("id")) { id = request["id"]; has_id = true; }
            if (!request.is_object() || !request.contains("sql") || !request["sql"].is_string()) fail("PROTOCOL", "request requires a string sql field");
            for (auto it = request.begin(); it != request.end(); ++it) if (it.key() != "id" && it.key() != "sql" && it.key() != "options") fail("PROTOCOL", "unknown request field: " + it.key());
            auto execution=request.contains("options") ? execution_options(request["options"],defaults) : defaults;
            response = result_json(engine.query(request["sql"].get<std::string>(),execution));
        } catch (const Error& e) { response = error_json(e.code, e.what()); }
        catch (const json::exception& e) { response = error_json("PROTOCOL", e.what()); }
        catch (const std::bad_alloc&) { response = error_json("RESOURCE", "allocation failed"); }
        catch (const std::exception& e) { response = error_json("INTERNAL", e.what()); }
        if (has_id) response["id"] = id;
        std::cout << response.dump() << '\n' << std::flush;
    }
}
void render_table(const Result& result) {
    for (std::size_t c = 0; c < result.columns.size(); ++c) { if (c) std::cout << "\t"; std::cout << result.columns[c].name; }
    std::cout << '\n';
    for (const auto& row : result.rows) {
        for (std::size_t c = 0; c < row.size(); ++c) {
            if (c) std::cout << "\t";
            if (row[c].is_null()) std::cout << "NULL";
            else if (row[c].type == Type::Int64) std::cout << row[c].integer();
            else std::cout << value_json(row[c]).dump();
        }
        std::cout << '\n';
    }
    std::cout << "(" << result.rows.size() << " rows)\n";
}
std::filesystem::path example_directory(const char* invoked) {
    std::filesystem::path executable;
#if defined(__APPLE__)
    std::uint32_t size=0;_NSGetExecutablePath(nullptr,&size);std::vector<char> buffer(size);
    if(_NSGetExecutablePath(buffer.data(),&size)==0) executable=buffer.data();
#elif defined(__linux__)
    std::error_code error;executable=std::filesystem::read_symlink("/proc/self/exe",error);
#endif
    if(executable.empty()) executable=std::filesystem::absolute(invoked);
    auto installed=executable.parent_path().parent_path()/"share/quarry/examples";
    if(std::filesystem::is_regular_file(installed/"catalog.json")) return installed;
    return QUARRY_EXAMPLE_DIR;
}
int run(int argc, char** argv) {
    if (argc == 1 || (argc == 2 && (std::string(argv[1]) == "--help" || std::string(argv[1]) == "help"))) { std::cout << help; return 0; }
    std::string command = argv[1];
    if(command=="bench") {
        std::filesystem::path manifest;bool validate=false;
        for(int i=2;i<argc;++i) {
            std::string flag=argv[i];
            if(flag=="--manifest" && manifest.empty() && i+1<argc) manifest=argv[++i];
            else if(flag=="--validate-only" && !validate) validate=true;
            else fail("CLI","bench requires --manifest PATH and optional --validate-only");
        }
        if(manifest.empty()) fail("CLI","bench requires --manifest PATH");
        return run_benchmark(manifest,validate);
    }
    if (command != "query" && command != "explain" && command != "session" && command != "demo") fail("UNSUPPORTED", "command not implemented: " + command);
    std::unordered_map<std::string,std::string> flags;
    std::unordered_set<std::string> valued = {"--catalog","--sql","--sql-file","--engine","--optimizer","--format","--memory-limit","--result-limit","--batch-size","--build-side","--prune","--pushdown","--fold","--join-reorder"};
    for (int i = 2; i < argc; ++i) {
        std::string flag = argv[i];
        if (flag == "--help") { std::cout << help; return 0; }
        if (flags.contains(flag)) fail("CLI", "duplicate flag: " + flag);
        if (flag == "--stdio" || flag=="--profile" || flag=="--analyze") { flags[flag] = "true"; continue; }
        if (!valued.contains(flag)) fail("CLI", "unknown/unimplemented flag: " + flag);
        if (++i == argc) fail("CLI", "missing value for " + flag);
        flags[flag] = argv[i];
    }
    ExecutionOptions execution;
    if(flags.contains("--engine")) execution=execution_options(json{{"engine",flags["--engine"]}},execution);
    if(flags.contains("--build-side")) execution=execution_options(json{{"build_side",flags["--build-side"]}},execution);
    if(flags.contains("--batch-size")) execution=execution_options(json{{"batch_size",size_arg(flags["--batch-size"])}},execution);
    for(const auto& key:{"optimizer","prune","pushdown","fold","join_reorder"}) {
        std::string flag="--"+std::string(key);if(flag=="--join_reorder") flag="--join-reorder";
        if(flags.contains(flag)) execution=execution_options(json{{key,flags[flag]}},execution);
    }
    execution.profile=flags.contains("--profile") || flags.contains("--analyze");
    if(flags.contains("--analyze") && command!="explain") fail("CLI","--analyze requires explain");
    if (flags.contains("--format") && flags["--format"] != "table" && flags["--format"] != "json") fail("CLI", "format must be table or json");
    Options options;
    if (flags.contains("--memory-limit")) options.memory_limit = size_arg(flags["--memory-limit"]);
    if (flags.contains("--result-limit")) options.result_limit = size_arg(flags["--result-limit"]);
    if (command == "demo") {
        if (!flags.empty()) fail("CLI", "demo accepts no options");
        auto examples=example_directory(argv[0]);Engine engine; engine.load_catalog(examples / "catalog.json");
        render_table(engine.query(read_bounded(examples / "query.sql",65536))); return 0;
    }
    if (!flags.contains("--catalog")) fail("CLI", "--catalog is required");
    if (command == "session") {
        if (!flags.contains("--stdio") || flags.contains("--sql") || flags.contains("--sql-file") || flags.contains("--format")) fail("CLI", "session requires --stdio and uses JSON-line requests");
    } else if (flags.contains("--stdio") || flags.contains("--sql") == flags.contains("--sql-file")) fail("CLI", "specify exactly one of --sql and --sql-file");
    Engine engine(options); engine.load_catalog(flags["--catalog"]);
    if (command == "session") { session(engine,execution); return 0; }
    auto sql = flags.contains("--sql") ? flags["--sql"] : read_bounded(flags["--sql-file"], 65536);
    if (command == "explain") {
        auto output=plan_json(engine.explain(sql,execution));
        if(flags.contains("--analyze")) output["result"]=result_json(engine.query(sql,execution));
        std::cout << output.dump() << '\n';return 0;
    }
    auto result = engine.query(sql,execution);
    if (flags.contains("--format") && flags["--format"] == "json") std::cout << result_json(result).dump() << '\n';
    else render_table(result);
    return 0;
}
}
int main(int argc, char** argv) {
    try { return run(argc,argv); }
    catch (const Error& e) { std::cout << error_json(e.code,e.what()).dump() << '\n'; return 1; }
    catch (const std::bad_alloc&) { std::cout << error_json("RESOURCE","allocation failed").dump() << '\n'; return 1; }
    catch (const std::exception& e) { std::cout << error_json("INTERNAL",e.what()).dump() << '\n'; return 1; }
}
