#pragma once
#include "sql/internal.hpp"
#include "common/wide.hpp"
#include <cmath>
#include <limits>
namespace quarry {
struct Accumulator {
    std::int64_t count = 0;
    WideSum integer_sum;
    double double_sum = 0;
    Value extreme;
    template<class T> void add_typed(const Expr& aggregate, T value, std::pmr::memory_resource* memory) {
        if (count == std::numeric_limits<std::int64_t>::max()) fail("NUMERIC", "aggregate count overflow");
        ++count;
        const auto& op = aggregate.op;
        if (op == "sum" || op == "avg") {
            if constexpr (std::is_same_v<T, std::int64_t>) integer_sum.add(value);
            else if constexpr (std::is_same_v<T, double>) { double_sum += value; if (!std::isfinite(double_sum)) fail("NUMERIC", "nonfinite DOUBLE accumulation"); }
        } else if (op == "min" || op == "max") {
            bool replace = count == 1;
            if (!replace) {
                int cmp;
                if constexpr (std::is_same_v<T,std::int64_t>) cmp = (value > extreme.integer()) - (value < extreme.integer());
                else if constexpr (std::is_same_v<T,double>) cmp = (value > extreme.real()) - (value < extreme.real());
                else if constexpr (std::is_same_v<T,bool>) cmp = int(value) - int(extreme.boolean());
                else { auto old = std::string_view(extreme.string()); cmp = value.compare(old); }
                replace = op == "min" ? cmp < 0 : cmp > 0;
            }
            if (replace) {
                if constexpr (std::is_same_v<T,std::int64_t>) extreme = Value::integer(value);
                else if constexpr (std::is_same_v<T,double>) extreme = Value::real(value);
                else if constexpr (std::is_same_v<T,bool>) extreme = Value::boolean(value);
                else extreme = Value::string(value, memory);
            }
        }
    }
    void add(const Expr& aggregate, const BoundQuery& query, RowRef row) {
        auto value = aggregate.left->kind == ExprKind::Star ? Value::integer(1) : evaluate(*aggregate.left, query, row);
        if (value.is_null()) return;
        if (value.type == Type::Int64) add_typed(aggregate,value.integer(),nullptr);
        else if (value.type == Type::Double) add_typed(aggregate,value.real(),nullptr);
        else if (value.type == Type::Bool) add_typed(aggregate,value.boolean(),nullptr);
        else add_typed(aggregate,std::string_view(value.string()),value.string().get_allocator().resource());
    }
    Value finish(const Expr& aggregate) const {
        if (aggregate.op == "count") return Value::integer(count);
        if (count == 0) return Value::null(aggregate.type);
        if (aggregate.op == "min" || aggregate.op == "max") return extreme;
        bool integer = aggregate.left->type == Type::Int64;
        if (aggregate.op == "avg") return Value::real(integer ? integer_sum.mean(count) : double_sum / static_cast<double>(count));
        return integer ? Value::integer(integer_sum.finish()) : Value::real(double_sum);
    }
};
struct KeyHash {
    std::size_t operator()(const Row& row) const noexcept {
        std::size_t hash = 0;
        for (const auto& v : row) {
            std::size_t part = 0x9e3779b9U;
            if (!v.is_null()) {
                if (v.type == Type::Int64) part = std::hash<std::int64_t>{}(v.integer());
                else if (v.type == Type::Bool) part = std::hash<bool>{}(v.boolean());
                else part = std::hash<std::string_view>{}(v.string());
            }
            hash ^= part + 0x9e3779b9U + (hash << 6U) + (hash >> 2U);
        }
        return hash;
    }
};
struct KeyEqual {
    bool operator()(const Row& a, const Row& b) const {
        if (a.size() != b.size()) return false;
        for (std::size_t i = 0; i < a.size(); ++i) {
            if (a[i].is_null() || b[i].is_null()) { if (a[i].is_null() != b[i].is_null()) return false; }
            else if (compare(a[i], b[i]) != 0) return false;
        }
        return true;
    }
};
struct Group {
    RowRef representative;
    std::pmr::vector<Accumulator> states;
    Group(RowRef row, std::size_t count, std::pmr::memory_resource* memory) : representative(row), states(memory) { states.resize(count); }
};
}
