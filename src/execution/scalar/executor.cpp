#include "sql/internal.hpp"
#include "execution/common/join.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>

namespace quarry {
Value evaluate(const Expr& e, const BoundQuery& query, RowRef row, const Row* aggregates) {
    switch (e.kind) {
    case ExprKind::Literal: return e.literal;
    case ExprKind::Column: return read_column(query,e.column,row);
    case ExprKind::Aggregate:
        if (!aggregates) fail("INTERNAL", "aggregate evaluated outside aggregate projection");
        return (*aggregates)[e.aggregate];
    case ExprKind::Star: fail("INTERNAL", "star evaluated as expression");
    default: break;
    }
    auto left = evaluate(*e.left, query, row, aggregates);
    if (e.kind == ExprKind::IsNull) return Value::boolean(e.op == "is null" ? left.is_null() : !left.is_null());
    if (e.kind == ExprKind::Cast) {
        if (left.is_null()) return Value::null(e.type);
        return Value::real(static_cast<double>(left.integer()));
    }
    if (e.kind == ExprKind::Unary) return e.op == "not" ? truth("not", left) : negate(left);
    auto right = evaluate(*e.right, query, row, aggregates);
    if (e.op == "and" || e.op == "or") return truth(e.op, left, right);
    if (e.op == "+" || e.op == "-" || e.op == "*" || e.op == "/") return numeric(e.op, left, right);
    return comparison(e.op, left, right);
}
namespace {
struct ScalarPipeline {
    const Table* scan = nullptr;
    const Expr* filter = nullptr;
    bool aggregate = false;
    const std::vector<SelectItem>* project = nullptr;
    const std::vector<Order>* sort = nullptr;
    std::optional<std::size_t> limit;
};
ScalarPipeline compile_scalar(const PlannedQuery& planned) {
    ScalarPipeline pipeline;
    const auto& q = planned.query;
    for (const auto& stage : planned.plan.physical) {
        switch (stage.operation) {
        case StageKind::Scan: pipeline.scan = q.table; break;
        case StageKind::InnerHashJoin: break;
        case StageKind::Filter:
            if(!stage.source.empty()) break;
            if (!q.where) fail("INTERNAL", "filter missing bound expression");
            pipeline.filter = q.where.get(); break;
        case StageKind::HashAggregate: pipeline.aggregate = true; break;
        case StageKind::Project: pipeline.project = &q.select; break;
        case StageKind::Sort: pipeline.sort = &q.order; break;
        case StageKind::Limit: pipeline.limit = q.limit; break;
        }
    }
    if (!pipeline.scan || !pipeline.project) fail("INTERNAL", "physical plan requires Scan and Project");
    return pipeline;
}
}
Result execute_scalar(const Engine& engine, const PlannedQuery& planned) {
    const auto& q = planned.query;
    const auto pipeline = compile_scalar(planned);
    Result result(engine.memory()); result.columns = q.output;
    auto* memory = engine.memory().get();
    Runtime runtime(planned,result,memory);
    auto check_cap = [&](std::size_t count) { if (count >= engine.options().result_limit) fail("RESOURCE", "materialized result/group row limit exceeded"); };
    auto emit = [&](RowRef row, const Row* aggregates) {
        auto& stats=runtime.get(StageKind::Project);Runtime::Scope scope(runtime,stats);++stats.input_rows;++stats.batches;
        check_cap(result.rows.size()); Row projected(memory); projected.reserve(pipeline.project->size());
        for (const auto& item : *pipeline.project) projected.push_back(evaluate(*item.expr, q, row, aggregates));
        result.rows.push_back(std::move(projected));++stats.output_rows;
    };
    std::pmr::unordered_map<Row, std::size_t, KeyHash, KeyEqual> lookup(memory);
    std::pmr::vector<Group> groups(memory);
    if (pipeline.aggregate && q.groups.empty()) { Runtime::Scope scope(runtime,runtime.get(StageKind::HashAggregate));check_cap(0); groups.emplace_back(0, q.aggregates.size(), memory); }
    // Competent scalar baseline: a single row traversal; binding/name resolution
    // is complete before this loop. No vector/batch wrapper is involved.
    std::size_t offsets[2]={0,0};
    auto source=[&](std::size_t index,std::pmr::vector<std::size_t>& rows) {
        const auto* table=index==0 ? q.table:q.right_table;if(!table || offsets[index]==table->row_count) return false;
        auto alias=index==0 ? q.alias:q.right_alias;auto row=offsets[index]++;
        {auto& stats=runtime.get(StageKind::Scan,alias);Runtime::Scope scope(runtime,stats);
            ++stats.input_rows;++stats.output_rows;++stats.batches;rows.push_back(row);}
        if(q.pushed[index]) {
            auto& stats=runtime.get(StageKind::Filter,alias);Runtime::Scope scope(runtime,stats);++stats.input_rows;++stats.batches;
            auto value=evaluate(*q.pushed[index],q,RowRef(row,row));
            if(value.is_null() || !value.boolean()) rows.clear();else ++stats.output_rows;
        }
        return true;
    };
    SourceStream left(memory,[&](auto& rows){return source(0,rows);});
    SourceStream right(memory,[&](auto& rows){return source(1,rows);});
    HashJoinCursor input(q,planned.execution.build_side,runtime,left,right);
    RowRef row;
    while(input.next(row)) {
        if (pipeline.filter) {
            auto& stats=runtime.get(StageKind::Filter);Runtime::Scope scope(runtime,stats);++stats.input_rows;++stats.batches;
            auto keep=evaluate(*pipeline.filter,q,row);if(keep.is_null() || !keep.boolean()) continue;++stats.output_rows;
        }
        ++result.filtered_rows;
        if (!pipeline.aggregate) { emit(row, nullptr); continue; }
        auto& aggregate_stats=runtime.get(StageKind::HashAggregate);Runtime::Scope aggregate_scope(runtime,aggregate_stats);++aggregate_stats.input_rows;++aggregate_stats.batches;
        std::size_t group = 0;
        if (!q.groups.empty()) {
            Row key(memory); key.reserve(q.groups.size());
            for (const auto& expr : q.groups) key.push_back(read_column(q,expr->column,row));
            auto found = lookup.find(key);
            if (found == lookup.end()) {
                check_cap(groups.size()); group = groups.size();
                groups.emplace_back(row, q.aggregates.size(), memory); lookup.emplace(std::move(key), group);
            } else group = found->second;
        }
        for (std::size_t a = 0; a < q.aggregates.size(); ++a) groups[group].states[a].add(*q.aggregates[a], q, row);
    }
    if (pipeline.aggregate) {
        runtime.get(StageKind::HashAggregate).output_rows=groups.size();
        for (const auto& group : groups) {
            Row values(memory);
            {Runtime::Scope scope(runtime,runtime.get(StageKind::HashAggregate));values.reserve(q.aggregates.size());
            for (std::size_t a = 0; a < q.aggregates.size(); ++a) values.push_back(group.states[a].finish(*q.aggregates[a]));}
            emit(group.representative, &values);
        }
    }
    if (pipeline.sort) {
        auto& stats=runtime.get(StageKind::Sort);Runtime::Scope scope(runtime,stats);stats.input_rows=stats.output_rows=result.rows.size();stats.batches=1;
        std::sort(result.rows.begin(), result.rows.end(), [&](const Row& a, const Row& b) {
            for (const auto& order : *pipeline.sort) {
                const auto& l = a[order.column]; const auto& r = b[order.column];
                if (l.is_null() || r.is_null()) {
                    if (l.is_null() == r.is_null()) continue;
                    return l.is_null() == order.nulls_first;
                }
                auto cmp = compare(l, r); if (cmp != 0) return order.descending ? cmp > 0 : cmp < 0;
            }
            return false;
        });
    }
    if(pipeline.limit) {
        auto& stats=runtime.get(StageKind::Limit);Runtime::Scope scope(runtime,stats);stats.input_rows=result.rows.size();stats.batches=1;
        if(result.rows.size()>*pipeline.limit) result.rows.erase(result.rows.begin()+static_cast<std::ptrdiff_t>(*pipeline.limit),result.rows.end());stats.output_rows=result.rows.size();
    }
    result.scanned_rows=offsets[0]+offsets[1];runtime.finish();
    return result;
}
}
