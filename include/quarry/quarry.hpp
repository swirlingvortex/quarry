#pragma once
#include <cstdint>
#include <filesystem>
#include <memory>
#include <memory_resource>
#include <stdexcept>
#include <string>
#include <string_view>
#include <variant>
#include <vector>
#include <unordered_map>
#include <span>
#include <optional>

namespace quarry {
struct Error : std::runtime_error {
    std::string code;
    Error(std::string code_, std::string message) : runtime_error(std::move(message)), code(std::move(code_)) {}
};
[[noreturn]] void fail(std::string code, std::string message);
std::string lower(std::string_view text);
bool valid_identifier(std::string_view text);
bool valid_utf8(std::string_view text);
std::string read_bounded(const std::filesystem::path& path, std::size_t limit);
void check_json_depth(std::string_view text, std::size_t limit = 128);

class Memory final : public std::pmr::memory_resource {
    std::size_t limit_, current_ = 0, peak_ = 0, allocated_ = 0;
    std::optional<std::size_t> failure_after_;
    void* do_allocate(std::size_t bytes, std::size_t alignment) override;
    void do_deallocate(void* ptr, std::size_t bytes, std::size_t alignment) override;
    bool do_is_equal(const std::pmr::memory_resource& other) const noexcept override { return this == &other; }
public:
    explicit Memory(std::size_t limit) : limit_(limit) {}
    void set_failure_after(std::optional<std::size_t> successes) { failure_after_=successes; }
    std::size_t allocated() const { return allocated_; }
    std::size_t current() const { return current_; }
    std::size_t peak() const { return peak_; }
};
enum class Type { Null, Int64, Double, Bool, String };
std::string type_name(Type type);
Type parse_type(std::string_view name);
using String = std::pmr::string;
struct ColumnView {
    Type type;
    std::span<const std::int64_t> integers;
    std::span<const double> doubles;
    std::span<const std::uint8_t> booleans;
    std::span<const String> strings;
    std::span<const std::uint64_t> validity;
    std::size_t source = 0;
    std::size_t* reads = nullptr;
    bool valid(std::size_t row) const { return (validity[row / 64] & (std::uint64_t(1) << (row % 64))) != 0; }
};
struct Value {
    Type type = Type::Null;
    std::variant<std::monostate, std::int64_t, double, bool, String> data;
    Value() = default;
    Value(const Value& other);
    Value& operator=(const Value& other);
    Value(Value&&) noexcept = default;
    Value& operator=(Value&&) = default;
    static Value null(Type type);
    static Value integer(std::int64_t value);
    static Value real(double value);
    static Value boolean(bool value);
    static Value string(std::string_view value, std::pmr::memory_resource* memory);
    bool is_null() const { return std::holds_alternative<std::monostate>(data); }
    std::int64_t integer() const { return std::get<std::int64_t>(data); }
    double real() const { return std::get<double>(data); }
    bool boolean() const { return std::get<bool>(data); }
    const String& string() const { return std::get<String>(data); }
};
Value numeric(std::string_view op, const Value& left, const Value& right);
Value negate(const Value& value);
Value truth(std::string_view op, const Value& left, const Value& right = Value{});
int compare(const Value& left, const Value& right); // non-null and same typed
Value comparison(std::string_view op, const Value& left, const Value& right);
Value parse_cell(std::string_view token, Type type, std::pmr::memory_resource* memory);

struct ColumnSpec { std::string name; Type type; bool nullable; };
class Column {
    using Ints = std::pmr::vector<std::int64_t>;
    using Doubles = std::pmr::vector<double>;
    using Bools = std::pmr::vector<std::uint8_t>;
    using Strings = std::pmr::vector<String>;
    std::variant<Ints, Doubles, Bools, Strings> values_;
    std::pmr::vector<std::uint64_t> validity_;
    std::pmr::memory_resource* memory_;
public:
    ColumnSpec spec;
    Column(ColumnSpec spec, std::pmr::memory_resource* memory);
    void append(const Value& value);
    Value at(std::size_t row) const;
    std::size_t size() const;
    ColumnView view() const;
};
struct Table {
    std::string name;
    std::pmr::vector<Column> columns;
    std::size_t row_count = 0;
    explicit Table(std::pmr::memory_resource* memory) : columns(memory) {}
};
struct OutputColumn { std::string name; Type type; };
using Row = std::pmr::vector<Value>;
struct Options {
    std::size_t memory_limit = 512ULL * 1024 * 1024;
    std::size_t result_limit = 100000;
};
enum class ExecutionMode { Scalar, Vector };
enum class BuildSide { Auto, Left, Right };
struct ExecutionOptions {
    ExecutionMode engine = ExecutionMode::Scalar;
    std::size_t batch_size = 1024;
    BuildSide build_side = BuildSide::Auto;
    bool optimizer=false, prune=true, pushdown=true, fold=true, join_reorder=true, profile=false;
};
enum class StageKind { Scan, InnerHashJoin, Filter, HashAggregate, Project, Sort, Limit };
struct PlanStage {
    std::size_t id;
    StageKind operation;
    std::string kind;
    std::vector<OutputColumn> output;
    std::string source;
    std::vector<std::size_t> bound_columns, inputs;
    std::vector<std::string> predicates;
};
struct RuleApplications {
    std::size_t column_pruning=0, predicate_pushdown=0, constant_folding=0, join_build_side=0;
};
struct OperatorStats {
    std::size_t id=0; std::string kind, source;
    std::size_t input_rows=0, output_rows=0, batches=0, columns_opened=0, columns_read=0, values_read=0;
    std::size_t build_rows=0, probe_rows=0, candidate_rows=0, accounted_allocation_bytes=0;
    std::uint64_t elapsed_ns=0;
};
struct Plan {
    std::vector<PlanStage> logical, optimized, physical;
    ExecutionOptions options;
    RuleApplications applications;
    ExecutionMode engine = ExecutionMode::Scalar;
    std::string build_side = "none", join_reason;
};
struct Result {
    std::shared_ptr<Memory> memory;
    std::vector<OutputColumn> columns;
    std::pmr::vector<Row> rows;
    Plan plan;
    std::vector<OperatorStats> operators;
    std::uint64_t planning_ns=0, execution_ns=0;
    std::size_t scanned_rows = 0, filtered_rows = 0, input_batches = 0;
    explicit Result(std::shared_ptr<Memory> owner) : memory(std::move(owner)), rows(memory.get()) {}
    Result(Result&&) = default;
    Result& operator=(Result&&) = delete;
    Result(const Result&) = delete;
};
class PreparedQuery {
    struct Impl;
    std::unique_ptr<Impl> impl_;
    explicit PreparedQuery(std::unique_ptr<Impl> impl);
    friend class Engine;
public:
    ~PreparedQuery();
    PreparedQuery(PreparedQuery&&) noexcept;
    PreparedQuery& operator=(PreparedQuery&&) noexcept;
    PreparedQuery(const PreparedQuery&)=delete;
    PreparedQuery& operator=(const PreparedQuery&)=delete;
    const Plan& plan() const;
};
class Engine {
    Options options_;
    std::shared_ptr<const int> catalog_identity_=std::make_shared<const int>(0);
    std::shared_ptr<Memory> memory_;
    std::unordered_map<std::string, std::unique_ptr<Table>> tables_;
public:
    explicit Engine(Options options = {}) : options_(options), memory_(std::make_shared<Memory>(options.memory_limit)) {}
    Engine(const Engine&) = delete;
    Engine& operator=(const Engine&) = delete;
    Engine(Engine&&) = delete;
    Engine& operator=(Engine&&) = delete;
    void load_catalog(const std::filesystem::path& manifest);
    const Table& table(std::string_view name) const;
    Result query(std::string_view sql, ExecutionOptions execution = {}) const;
    PreparedQuery prepare(std::string_view sql, ExecutionOptions execution = {}) const;
    Result execute(const PreparedQuery& prepared) const;
    Plan explain(std::string_view sql, ExecutionOptions execution = {}) const;
    const std::shared_ptr<Memory>& memory() const { return memory_; }
    const Options& options() const { return options_; }
};
}
