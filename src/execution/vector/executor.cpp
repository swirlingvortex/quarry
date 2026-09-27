#include "execution/vector/batch.hpp"
#include "execution/common/join.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <unordered_map>
namespace quarry {
namespace {
std::int64_t integer_op(std::string_view op,std::int64_t a,std::int64_t b) {
    std::int64_t result;
    bool overflow=op=="+" ? __builtin_add_overflow(a,b,&result) : op=="-" ? __builtin_sub_overflow(a,b,&result) : __builtin_mul_overflow(a,b,&result);
    if(overflow) fail("NUMERIC","INT64 arithmetic overflow");return result;
}
double double_op(std::string_view op,double a,double b) {
    if(op=="/" && b==0) fail("NUMERIC","division by zero");
    double result=op=="+" ? a+b : op=="-" ? a-b : op=="*" ? a*b : a/b;
    if(!std::isfinite(result)) fail("NUMERIC","nonfinite DOUBLE result");return result;
}
bool comparison_op(std::string_view op,int c) { return op=="=" ? c==0 : (op=="!=" || op=="<>") ? c!=0 : op=="<" ? c<0 : op=="<=" ? c<=0 : op==">" ? c>0 : c>=0; }
template<class T> void compare_vectors(const Expr& e,const Vector& a,const Vector& b,Vector& out) {
    const auto& left=a.values<T>(); const auto& right=b.values<T>(); auto& values=out.values<std::uint8_t>();
    for(std::size_t i=0;i<out.size();++i) if(!out.faults[i] && (out.valid[i]=a.valid[i] && b.valid[i])) values[i]=static_cast<std::uint8_t>(comparison_op(e.op,int(left[i]>right[i])-int(left[i]<right[i])));
}
void assign_value(Vector& vector,std::size_t row,const Value& value) {
    if(value.is_null()) return;
    vector.valid[row]=1;
    switch(value.type) {
    case Type::Int64: vector.values<std::int64_t>()[row]=value.integer();break;
    case Type::Double: vector.values<double>()[row]=value.real();break;
    case Type::Bool: vector.values<std::uint8_t>()[row]=static_cast<std::uint8_t>(value.boolean());break;
    case Type::String: vector.values<std::string_view>()[row]=value.string();break;
    case Type::Null: break;
    }
}
}
Vector evaluate_batch(const Expr& e,const std::pmr::vector<ColumnView>& columns,const Batch& batch,std::pmr::memory_resource* memory,const std::pmr::vector<Vector>* aggregates) {
    const auto n=batch.selection.size(); Vector out(e.type,n,memory);
    if(e.kind==ExprKind::Column) {
        const auto& col=columns[e.slot];if(col.reads) *col.reads+=n;
        for(std::size_t i=0;i<n;++i) out.valid[i]=static_cast<std::uint8_t>(col.valid(batch.rows[batch.selection[i]].at(col.source)));
        auto gather=[&](const auto& source,auto& destination) { for(std::size_t i=0;i<n;++i) if(out.valid[i]) destination[i]=source[batch.rows[batch.selection[i]].at(col.source)]; };
        switch(e.type) {
        case Type::Int64: gather(col.integers,out.values<std::int64_t>());break;
        case Type::Double: gather(col.doubles,out.values<double>());break;
        case Type::Bool: gather(col.booleans,out.values<std::uint8_t>());break;
        case Type::String: gather(col.strings,out.values<std::string_view>());break;
        case Type::Null: break;
        }
        return out;
    }
    if(e.kind==ExprKind::Literal) { for(std::size_t i=0;i<n;++i) assign_value(out,i,e.literal);return out; }
    if(e.kind==ExprKind::Aggregate) {
        if(!aggregates) fail("INTERNAL","batch aggregate evaluated without group values");
        const auto& source=(*aggregates)[e.aggregate];
        // Group aggregate arrays are already compact and aligned with selection.
        out.valid=source.valid;out.faults=source.faults;out.data=source.data;return out;
    }
    if(e.kind==ExprKind::Star) fail("INTERNAL","batch star was not expanded");
    auto left=evaluate_batch(*e.left,columns,batch,memory,aggregates);
    out.faults=left.faults;
    if(e.kind==ExprKind::IsNull) {
        for(std::size_t i=0;i<n;++i) { out.valid[i]=1;out.values<std::uint8_t>()[i]=static_cast<std::uint8_t>(e.op=="is null" ? !left.valid[i] : bool(left.valid[i])); }return out;
    }
    if(e.kind==ExprKind::Cast) {
        for(std::size_t i=0;i<n;++i) if(!out.faults[i] && (out.valid[i]=left.valid[i])) out.values<double>()[i]=static_cast<double>(left.values<std::int64_t>()[i]);return out;
    }
    if(e.kind==ExprKind::Unary) {
        out.valid=left.valid;
        if(e.op=="not") { for(std::size_t i=0;i<n;++i) if(out.valid[i]) out.values<std::uint8_t>()[i]=!left.values<std::uint8_t>()[i]; }
        else if(e.type==Type::Int64) { for(std::size_t i=0;i<n;++i) if(out.valid[i] && !out.faults[i]) {
            if(left.values<std::int64_t>()[i]==INT64_MIN) {out.faults[i]=4;out.valid[i]=0;}
            else out.values<std::int64_t>()[i]=-left.values<std::int64_t>()[i];
        } }
        else { for(std::size_t i=0;i<n;++i) if(out.valid[i]) out.values<double>()[i]=-left.values<double>()[i]; }
        return out;
    }
    auto right=evaluate_batch(*e.right,columns,batch,memory,aggregates);
    for(std::size_t i=0;i<n;++i) if(!out.faults[i]) out.faults[i]=right.faults[i];
    if(e.op=="and" || e.op=="or") {
        for(std::size_t i=0;i<n;++i) {
            if(out.faults[i]) continue;
            int a=left.valid[i] ? left.values<std::uint8_t>()[i] : -1, b=right.valid[i] ? right.values<std::uint8_t>()[i] : -1;
            int value=e.op=="and" ? ((a==0 || b==0) ? 0 : (a<0 || b<0) ? -1 : 1) : ((a==1 || b==1) ? 1 : (a<0 || b<0) ? -1 : 0);
            if(value>=0) { out.valid[i]=1;out.values<std::uint8_t>()[i]=static_cast<std::uint8_t>(value); }
        }return out;
    }
    if(e.op=="+" || e.op=="-" || e.op=="*" || e.op=="/") {
        // Capture faults by selected lane. Row-domain consumers decide which
        // error precedes a later result/group cap, independent of batch size.
        for(std::size_t i=0;i<n;++i) {
            if(out.faults[i] || !(out.valid[i]=left.valid[i] && right.valid[i])) continue;
            try {
                if(e.type==Type::Int64) out.values<std::int64_t>()[i]=integer_op(e.op,left.values<std::int64_t>()[i],right.values<std::int64_t>()[i]);
                else if(left.type==Type::Int64) out.values<double>()[i]=double_op(e.op,static_cast<double>(left.values<std::int64_t>()[i]),static_cast<double>(right.values<std::int64_t>()[i]));
                else out.values<double>()[i]=double_op(e.op,left.values<double>()[i],right.values<double>()[i]);
            } catch(const Error& error) {
                if(error.code!="NUMERIC") throw;
                out.valid[i]=0;
                out.faults[i]=e.type==Type::Int64 ? 1 : std::string_view(error.what())=="division by zero" ? 2 : 3;
            }
        }return out;
    }
    switch(left.type) {
    case Type::Int64: compare_vectors<std::int64_t>(e,left,right,out);break;
    case Type::Double: compare_vectors<double>(e,left,right,out);break;
    case Type::Bool: compare_vectors<std::uint8_t>(e,left,right,out);break;
    case Type::String: compare_vectors<std::string_view>(e,left,right,out);break;
    case Type::Null: break;
    }
    return out;
}
Result execute_vector(const Engine& engine,const PlannedQuery& planned) {
    const auto& q=planned.query;auto* memory=engine.memory().get();
    const Expr* filter=nullptr;bool aggregate=false,sort=false;std::optional<std::size_t> limit;
    for(const auto& stage:planned.plan.physical) {
        if(stage.operation==StageKind::Filter && stage.source.empty()) filter=q.where.get();
        if(stage.operation==StageKind::HashAggregate) aggregate=true;
        if(stage.operation==StageKind::Sort) sort=true;
        if(stage.operation==StageKind::Limit) limit=q.limit;
    }
    Result result(engine.memory());result.columns=q.output;
    Runtime runtime(planned,result,memory);const auto& views=runtime.views;
    std::pmr::vector<Vector> output(memory);
    {Runtime::Scope scope(runtime,runtime.get(StageKind::Project));for(const auto& column:q.output) output.emplace_back(column.type,0,memory);}
    auto row_cap=engine.options().result_limit;std::size_t produced=0;
    auto check_cap=[&](std::size_t count) { if(count>=row_cap) fail("RESOURCE","materialized result/group row limit exceeded"); };
    auto project=[&](Batch& batch,const std::pmr::vector<Vector>* values) {
        if(batch.selection.empty()) return;
        auto& stats=runtime.get(StageKind::Project);Runtime::Scope scope(runtime,stats);stats.input_rows+=batch.selection.size();++stats.batches;
        check_cap(produced);auto allowed=std::min(batch.selection.size(),row_cap-produced);bool overflow=allowed<batch.selection.size();
        batch.selection.resize(allowed);
        std::pmr::vector<Vector> projected(memory);
        for(const auto& item:q.select) projected.push_back(evaluate_batch(*item.expr,views,batch,memory,values));
        for(std::size_t i=0;i<allowed;++i) for(const auto& col:projected) col.throw_if_fault(i);
        for(std::size_t c=0;c<projected.size();++c) output[c].append(projected[c]);
        stats.output_rows+=allowed;produced+=allowed;if(overflow) fail("RESOURCE","materialized result/group row limit exceeded");
    };
    std::pmr::unordered_map<Row,std::size_t,KeyHash,KeyEqual> lookup(memory);
    std::pmr::vector<Group> groups(memory);
    if(aggregate && q.groups.empty()) { Runtime::Scope scope(runtime,runtime.get(StageKind::HashAggregate));check_cap(0);groups.emplace_back(0,q.aggregates.size(),memory); }
    std::size_t offsets[2]={0,0};
    auto source=[&](std::size_t index,std::pmr::vector<std::size_t>& rows) {
        const auto* table=index==0 ? q.table:q.right_table;if(!table || offsets[index]==table->row_count) return false;
        auto alias=index==0 ? q.alias:q.right_alias;auto count=std::min(planned.execution.batch_size,table->row_count-offsets[index]);
        Batch scanned(memory);
        {auto& stats=runtime.get(StageKind::Scan,alias);Runtime::Scope scope(runtime,stats);
            scanned.reset(offsets[index],count);if(index==1) for(auto& row:scanned.rows) row.right=row.left;
            offsets[index]+=count;stats.input_rows+=count;stats.output_rows+=count;++stats.batches;}
        if(q.pushed[index]) {
            auto& stats=runtime.get(StageKind::Filter,alias);Runtime::Scope scope(runtime,stats);stats.input_rows+=count;++stats.batches;
            auto keep=evaluate_batch(*q.pushed[index],views,scanned,memory);std::size_t selected=0;
            for(std::size_t i=0;i<count;++i) {keep.throw_if_fault(i);if(keep.valid[i] && keep.values<std::uint8_t>()[i]) scanned.selection[selected++]=i;}
            scanned.selection.resize(selected);stats.output_rows+=selected;
        }
        for(auto i:scanned.selection) rows.push_back(scanned.rows[i].at(index));return true;
    };
    SourceStream left(memory,[&](auto& rows){return source(0,rows);});
    SourceStream right(memory,[&](auto& rows){return source(1,rows);});
    Batch batch(memory);HashJoinCursor input(q,planned.execution.build_side,runtime,left,right);
    while(input.next_batch(batch.rows,planned.execution.batch_size)) {
        batch.row_count=batch.rows.size();batch.selection.resize(batch.row_count);std::iota(batch.selection.begin(),batch.selection.end(),0);
        ++result.input_batches;
        if(filter) {
            auto& stats=runtime.get(StageKind::Filter);Runtime::Scope scope(runtime,stats);stats.input_rows+=batch.selection.size();++stats.batches;
            auto keep=evaluate_batch(*filter,views,batch,memory);std::size_t count=0;
            for(std::size_t i=0;i<batch.selection.size();++i) {
                keep.throw_if_fault(i);
                if(keep.valid[i] && keep.values<std::uint8_t>()[i]) batch.selection[count++]=batch.selection[i];
            }
            batch.selection.resize(count);stats.output_rows+=count;
        }
        result.filtered_rows+=batch.selection.size();if(batch.selection.empty()) continue;
        if(!aggregate) { project(batch,nullptr);continue; }
        auto& aggregate_stats=runtime.get(StageKind::HashAggregate);Runtime::Scope aggregate_scope(runtime,aggregate_stats);aggregate_stats.input_rows+=batch.selection.size();++aggregate_stats.batches;
        std::pmr::vector<Vector> keys(memory);for(const auto& key:q.groups) keys.push_back(evaluate_batch(*key,views,batch,memory));
        std::pmr::vector<Vector> arguments(memory);
        for(const auto* expr:q.aggregates) {
            if(expr->left->kind==ExprKind::Star) arguments.emplace_back(Type::Int64,0,memory);
            else arguments.push_back(evaluate_batch(*expr->left,views,batch,memory));
        }
        for(std::size_t i=0;i<batch.selection.size();++i) {
            std::size_t id=0;
            if(!keys.empty()) {
                Row key(memory);for(const auto& col:keys) key.push_back(col.box(i,memory));
                auto found=lookup.find(key);
                if(found==lookup.end()) { check_cap(groups.size());id=groups.size();groups.emplace_back(batch.rows[batch.selection[i]],q.aggregates.size(),memory);lookup.emplace(std::move(key),id); }
                else id=found->second;
            }
            // Expression arrays are typed; only hash-state traversal is row
            // ordered, matching scalar group-cap and accumulation semantics.
            for(std::size_t a=0;a<q.aggregates.size();++a) {
                const auto& expr=*q.aggregates[a];auto& state=groups[id].states[a];const auto& values=arguments[a];
                if(expr.left->kind==ExprKind::Star) { state.add_typed(expr,std::int64_t(1),memory);continue; }
                values.throw_if_fault(i);if(!values.valid[i]) continue;
                switch(values.type) {
                case Type::Int64: state.add_typed(expr,values.values<std::int64_t>()[i],memory);break;
                case Type::Double: state.add_typed(expr,values.values<double>()[i],memory);break;
                case Type::Bool: state.add_typed(expr,bool(values.values<std::uint8_t>()[i]),memory);break;
                case Type::String: state.add_typed(expr,values.values<std::string_view>()[i],memory);break;
                case Type::Null: break;
                }
            }
        }
    }
    if(aggregate) {
        runtime.get(StageKind::HashAggregate).output_rows=groups.size();
        for(std::size_t start=0;start<groups.size();start+=planned.execution.batch_size) {
            auto count=std::min(planned.execution.batch_size,groups.size()-start);
            std::pmr::vector<Vector> values(memory);
            {Runtime::Scope scope(runtime,runtime.get(StageKind::HashAggregate));batch.reset(0,count);
            for(const auto* expr:q.aggregates) values.emplace_back(expr->type,count,memory);
            for(std::size_t i=0;i<count;++i) {
                batch.rows[i]=groups[start+i].representative;
                for(std::size_t a=0;a<q.aggregates.size();++a) {
                    auto& state=groups[start+i].states[a];
                    if(q.aggregates[a]->type==Type::String) assign_value(values[a],i,state.extreme);
                    else assign_value(values[a],i,state.finish(*q.aggregates[a]));
                }
            }
            }
            project(batch,&values);
        }
    }
    std::pmr::vector<std::size_t> order(memory);
    {Runtime::Scope scope(runtime,runtime.get(sort ? StageKind::Sort:StageKind::Project));order.resize(produced);std::iota(order.begin(),order.end(),0);}
    if(sort) {
    auto& stats=runtime.get(StageKind::Sort);Runtime::Scope scope(runtime,stats);stats.input_rows=stats.output_rows=produced;stats.batches=1;
    std::sort(order.begin(),order.end(),[&](auto a,auto b) {
        for(const auto& rule:q.order) {
            const auto& col=output[rule.column];
            if(!col.valid[a] || !col.valid[b]) { if(col.valid[a]==col.valid[b]) continue;return !bool(col.valid[a])==rule.nulls_first; }
            int c=col.compare_at(a,b);if(c) return rule.descending ? c>0 : c<0;
        }return false;
    });
    }
    if(limit) {
        auto& stats=runtime.get(StageKind::Limit);Runtime::Scope scope(runtime,stats);stats.input_rows=order.size();stats.batches=1;
        if(order.size()>*limit) order.resize(*limit);stats.output_rows=order.size();
    }
    // Shared owning sink boundary; all vector hot paths above are typed.
    {Runtime::Scope scope(runtime,runtime.get(StageKind::Project));
    for(auto row:order) { Row values(memory);values.reserve(output.size());for(const auto& col:output) values.push_back(col.box(row,memory));result.rows.push_back(std::move(values)); }
    }
    result.scanned_rows=offsets[0]+offsets[1];runtime.finish();
    return result;
}
}
