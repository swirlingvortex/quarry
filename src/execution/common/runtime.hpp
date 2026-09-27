#pragma once
#include "sql/internal.hpp"
#include <chrono>
namespace quarry {
// Query-local bounded metadata. Allocation and timing scopes are inclusive;
// they overlap when a join pulls its child scans and must never be summed.
class Runtime {
    const PlannedQuery& planned_;
    Result& result_;
public:
    Memory* memory;
    std::pmr::vector<ColumnView> views;
    Runtime(const PlannedQuery& planned,Result& result,Memory* resource)
        : planned_(planned),result_(result),memory(resource),views(resource) {
        for(const auto& binding:planned.query.columns) {binding.reads=0;binding.view=nullptr;}
        result_.plan=planned.plan;
        for(const auto& stage:planned.plan.physical) {
            OperatorStats stats;stats.id=stage.id;stats.kind=stage.kind;stats.source=stage.source;result_.operators.push_back(std::move(stats));
        }
        // Fixed capacity keeps bindings' compiled descriptor pointers stable.
        {auto& stats=get(StageKind::Scan,planned.query.alias);Scope scope(*this,stats);views.reserve(planned.query.active_columns.size());}
        for(auto id:planned.query.active_columns) {
            const auto& binding=planned.query.columns[id];auto& stats=get(StageKind::Scan,binding.qualifier);
            Scope scope(*this,stats);auto view=binding.column->view();view.source=binding.source;view.reads=&binding.reads;
            views.push_back(view);binding.view=&views.back();++stats.columns_opened;
        }
    }
    OperatorStats& get(StageKind op,std::string_view source="") {
        for(const auto& stage:planned_.plan.physical) if(stage.operation==op && stage.source==source) return result_.operators[stage.id];
        fail("INTERNAL","operator statistics stage missing");
    }
    class Scope {
        Runtime& runtime_;OperatorStats& stats_;std::size_t allocated_;
        std::chrono::steady_clock::time_point start_;
    public:
        Scope(Runtime& runtime,OperatorStats& stats):runtime_(runtime),stats_(stats),allocated_(runtime.memory->allocated()),
            start_(runtime.planned_.execution.profile ? std::chrono::steady_clock::now():std::chrono::steady_clock::time_point{}) {}
        ~Scope() {
            stats_.accounted_allocation_bytes+=runtime_.memory->allocated()-allocated_;
            if(runtime_.planned_.execution.profile) stats_.elapsed_ns+=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start_).count());
        }
    };
    void finish() {
        for(const auto& binding:planned_.query.columns) {
            auto& stats=get(StageKind::Scan,binding.qualifier);stats.values_read+=binding.reads;if(binding.reads) ++stats.columns_read;
        }
    }
};
inline Value read_column(const BoundQuery& q,std::size_t id,RowRef row) {
    const auto& binding=q.columns[id];++binding.reads;
    if(!binding.view) fail("INTERNAL","column descriptor was not opened");
    const auto& view=*binding.view;auto index=row.at(view.source);
    if(!view.valid(index)) return Value::null(view.type);
    switch(view.type) {
    case Type::Int64: return Value::integer(view.integers[index]);
    case Type::Double: return Value::real(view.doubles[index]);
    case Type::Bool: return Value::boolean(view.booleans[index]!=0);
    case Type::String: return Value::string(view.strings[index],view.strings[index].get_allocator().resource());
    case Type::Null: return Value::null(view.type);
    }
    fail("INTERNAL","invalid opened column type");
}
}
