#pragma once
#include "quarry/quarry.hpp"
#include <optional>
namespace quarry {
enum class ExprKind { Literal, Column, Unary, Binary, IsNull, Cast, Aggregate, Star };
struct Expr {
    ExprKind kind = ExprKind::Literal;
    std::string op, name, qualifier;
    Value literal;
    std::unique_ptr<Expr> left, right;
    Type type = Type::Null;
    std::size_t column = 0, slot = 0, aggregate = 0;
};
struct SelectItem { std::unique_ptr<Expr> expr; std::string alias; };
struct Order {
    std::string name;
    std::optional<std::size_t> position;
    bool descending = false, nulls_first = false;
    std::size_t column = 0;
};
struct RowRef {
    std::size_t left, right;
    RowRef(std::size_t l=0,std::size_t r=0) : left(l),right(r) {}
    std::size_t at(std::size_t source) const { return source==0 ? left : right; }
};
struct ColumnBinding {
    const Column* column;
    std::size_t source;
    std::string qualifier;
    mutable std::size_t reads=0;
    mutable const ColumnView* view=nullptr;
};
struct BoundQuery {
    std::string table_name, alias;
    const Table* table = nullptr;
    const Table* right_table = nullptr;
    std::string right_name, right_alias;
    std::unique_ptr<Expr> join;
    std::vector<std::pair<std::size_t,std::size_t>> join_keys;
    std::vector<ColumnBinding> columns;
    std::vector<SelectItem> select;
    std::unique_ptr<Expr> where;
    std::unique_ptr<Expr> pushed[2];
    std::vector<std::size_t> active_columns;
    std::vector<std::unique_ptr<Expr>> groups;
    std::vector<Order> order;
    std::optional<std::size_t> limit;
    std::vector<Expr*> aggregates;
    bool aggregation = false;
    std::vector<OutputColumn> output;
};
BoundQuery bind_query(const Engine& engine, std::string_view sql);
bool potentially_failing(const Expr& expr);
std::string expression_label(const Expr& expr);
std::string join_swap_block_reason(const BoundQuery& query);
Plan make_plan(const BoundQuery& query, ExecutionOptions execution = {});
struct PlannedQuery { BoundQuery query; Plan plan; ExecutionOptions execution; };
PlannedQuery plan_query(const Engine& engine, std::string_view sql, ExecutionOptions execution = {});
Result execute_scalar(const Engine& engine, const PlannedQuery& planned);
Result execute_vector(const Engine& engine, const PlannedQuery& planned);
Value evaluate(const Expr& expr, const BoundQuery& query, RowRef row,
               const Row* aggregates = nullptr);
}
