#include "sql/internal.hpp"
#include <algorithm>
#include <chrono>
#include <functional>
#include <set>
namespace quarry {
namespace {
void visit(Expr* e,const std::function<void(Expr&)>& fn) {
    if(!e) return;fn(*e);visit(e->left.get(),fn);visit(e->right.get(),fn);
}
void expressions(BoundQuery& q,const std::function<void(Expr&)>& fn) {
    for(auto& s:q.select) visit(s.expr.get(),fn);
    visit(q.where.get(),fn);visit(q.join.get(),fn);
    for(auto& p:q.pushed) visit(p.get(),fn);
    for(auto& g:q.groups) visit(g.get(),fn);
}
bool literal_tree(const Expr& e) {
    if(e.kind==ExprKind::Column || e.kind==ExprKind::Aggregate || e.kind==ExprKind::Star) return false;
    return (!e.left || literal_tree(*e.left)) && (!e.right || literal_tree(*e.right));
}
void fold(std::unique_ptr<Expr>& e,const BoundQuery& q,std::size_t& count) {
    if(!e) return;fold(e->left,q,count);fold(e->right,q,count);
    if(e->kind==ExprKind::Literal || !literal_tree(*e)) return;
    try {
        auto value=evaluate(*e,q,RowRef{});auto replacement=std::make_unique<Expr>();
        replacement->type=e->type;replacement->literal=std::move(value);e=std::move(replacement);++count;
    } catch(const Error& error) { if(error.code!="NUMERIC") throw; } // Failed literals retain their evaluation domain.
}
unsigned sources(const Expr& e,const BoundQuery& q) {
    unsigned mask=e.kind==ExprKind::Column ? 1U<<q.columns[e.column].source : 0;
    if(e.left) mask|=sources(*e.left,q);if(e.right) mask|=sources(*e.right,q);return mask;
}
void append_and(std::unique_ptr<Expr>& target,std::unique_ptr<Expr> term) {
    if(!target) {target=std::move(term);return;}
    auto e=std::make_unique<Expr>();e->kind=ExprKind::Binary;e->op="and";e->type=Type::Bool;
    e->left=std::move(target);e->right=std::move(term);target=std::move(e);
}
void push(std::unique_ptr<Expr> e,BoundQuery& q,RuleApplications& counts) {
    if(e->kind==ExprKind::Binary && e->op=="and") {push(std::move(e->left),q,counts);push(std::move(e->right),q,counts);return;}
    auto mask=sources(*e,q);
    if(mask==3) append_and(q.where,std::move(e));
    else {append_and(q.pushed[mask==2 ? 1 : 0],std::move(e));++counts.predicate_pushdown;}
}
}
Plan make_plan(const BoundQuery& q,ExecutionOptions execution) {
    Plan p;p.engine=execution.engine;p.options=execution;
    std::vector<OutputColumn> schema;std::vector<std::size_t> ids;
    auto add=[&](StageKind op,std::string kind,const std::vector<OutputColumn>& output,std::string source,
                 std::vector<std::size_t> columns,std::vector<std::size_t> inputs,std::vector<std::string> predicates={}) {
        auto id=p.logical.size();p.logical.push_back({id,op,std::move(kind),output,std::move(source),std::move(columns),std::move(inputs),std::move(predicates)});return id;
    };
    std::vector<std::size_t> roots;
    for(std::size_t source=0;source<(q.right_table ? 2U:1U);++source) {
        std::vector<OutputColumn> local;std::vector<std::size_t> columns;
        for(auto id:q.active_columns) if(q.columns[id].source==source) {
            const auto& spec=q.columns[id].column->spec;local.push_back({spec.name,spec.type});columns.push_back(id);
        }
        auto name=source==0 ? q.alias:q.right_alias;
        auto root=add(StageKind::Scan,"Scan",local,name,columns,{});
        if(q.pushed[source]) root=add(StageKind::Filter,"Filter",local,name,columns,{root},{expression_label(*q.pushed[source])});
        roots.push_back(root);schema.insert(schema.end(),local.begin(),local.end());ids.insert(ids.end(),columns.begin(),columns.end());
    }
    auto root=roots[0];
    if(q.right_table) {
        root=add(StageKind::InnerHashJoin,"InnerHashJoin",schema,"",ids,roots,{expression_label(*q.join)});
        p.build_side=execution.build_side==BuildSide::Left ? "left":"right";
    }
    if(q.where) root=add(StageKind::Filter,"Filter",schema,"",ids,{root},{expression_label(*q.where)});
    if(q.aggregation) {
        schema.clear();for(const auto& g:q.groups) schema.push_back({g->name,g->type});
        for(const auto* a:q.aggregates) schema.push_back({expression_label(*a),a->type});
        root=add(StageKind::HashAggregate,"HashAggregate",schema,"",ids,{root});
    }
    std::vector<std::string> projects;for(const auto& item:q.select) projects.push_back(expression_label(*item.expr));
    root=add(StageKind::Project,"Project",q.output,"",ids,{root},projects);
    if(!q.order.empty()) root=add(StageKind::Sort,"Sort",q.output,"",{}, {root});
    if(q.limit) add(StageKind::Limit,"Limit",q.output,"",{}, {root});
    p.optimized=p.logical;p.physical=p.logical;
    for(auto& stage:p.physical) stage.kind=(execution.engine==ExecutionMode::Scalar ? "Scalar":"Vector")+stage.kind;
    return p;
}
PlannedQuery plan_query(const Engine& engine,std::string_view sql,ExecutionOptions execution) {
    if(execution.batch_size==0 || execution.batch_size>65536) fail("CLI","batch size must be in 1..65536");
    auto q=bind_query(engine,sql);for(std::size_t i=0;i<q.columns.size();++i) q.active_columns.push_back(i);
    auto original=make_plan(q,execution).logical;RuleApplications counts;
    if(execution.optimizer && execution.fold) {
        for(auto& item:q.select) fold(item.expr,q,counts.constant_folding);
        fold(q.where,q,counts.constant_folding);
    }
    // Guard before splitting WHERE: pushing even a total sibling could suppress
    // an eagerly evaluated failing conjunct, or expose it on unmatched rows.
    auto swap_guard=join_swap_block_reason(q);
    if(execution.optimizer && execution.pushdown && q.right_table && q.where && !potentially_failing(*q.where))
        push(std::move(q.where),q,counts);
    if(execution.optimizer && execution.prune) {
        std::set<std::size_t> needed;expressions(q,[&](Expr& e){if(e.kind==ExprKind::Column) needed.insert(e.column);});
        counts.column_pruning=q.active_columns.size()-needed.size();q.active_columns.assign(needed.begin(),needed.end());
    }
    expressions(q,[&](Expr& e) {if(e.kind==ExprKind::Column) {
        auto it=std::find(q.active_columns.begin(),q.active_columns.end(),e.column);
        if(it==q.active_columns.end()) fail("INTERNAL","required column pruned");e.slot=static_cast<std::size_t>(it-q.active_columns.begin());
    }});
    std::string reason;
    if(q.right_table) {
        if(execution.build_side==BuildSide::Left && !swap_guard.empty()) fail("UNSUPPORTED","unsafe left build: "+swap_guard);
        if(execution.build_side!=BuildSide::Auto) reason="explicit physical build-side request";
        else if(execution.optimizer && execution.join_reorder) {
            if(!swap_guard.empty()) {execution.build_side=BuildSide::Right;reason=swap_guard;}
            else {execution.build_side=q.table->row_count<q.right_table->row_count ? BuildSide::Left:BuildSide::Right;
                reason="smaller base input cardinality; ties use right build";++counts.join_build_side;}
        } else {execution.build_side=BuildSide::Right;reason="default right build preserves left probe order";}
    }
    auto plan=make_plan(q,execution);plan.logical=std::move(original);plan.join_reason=reason;plan.applications=counts;
    return {std::move(q),std::move(plan),execution};
}
struct PreparedQuery::Impl {
    // The AST can own PMR strings and must die before its resource owner.
    std::shared_ptr<Memory> memory;
    std::weak_ptr<const int> catalog_identity;
    PlannedQuery planned;
    Impl(std::shared_ptr<Memory> owner,std::weak_ptr<const int> identity,PlannedQuery query)
        :memory(std::move(owner)),catalog_identity(std::move(identity)),planned(std::move(query)) {}
};
PreparedQuery::PreparedQuery(std::unique_ptr<Impl> impl):impl_(std::move(impl)) {}
PreparedQuery::~PreparedQuery()=default;
PreparedQuery::PreparedQuery(PreparedQuery&&) noexcept=default;
PreparedQuery& PreparedQuery::operator=(PreparedQuery&&) noexcept=default;
const Plan& PreparedQuery::plan() const {
    if(!impl_) fail("BIND","moved-from prepared query");return impl_->planned.plan;
}
PreparedQuery Engine::prepare(std::string_view sql,ExecutionOptions options) const {
    return PreparedQuery(std::make_unique<PreparedQuery::Impl>(memory_,catalog_identity_,plan_query(*this,sql,options)));
}
Result Engine::execute(const PreparedQuery& prepared) const {
    if(!prepared.impl_) fail("BIND","moved-from prepared query");
    if(prepared.impl_->catalog_identity.lock()!=catalog_identity_) fail("BIND","prepared query belongs to a different or replaced catalog");
    const auto& planned=prepared.impl_->planned;
    using Clock=std::chrono::steady_clock;auto start=planned.execution.profile ? Clock::now():Clock::time_point{};
    auto result=planned.execution.engine==ExecutionMode::Scalar ? execute_scalar(*this,planned):execute_vector(*this,planned);
    if(planned.execution.profile) result.execution_ns=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count());
    return result;
}
Plan Engine::explain(std::string_view sql,ExecutionOptions execution) const {return plan_query(*this,sql,execution).plan;}
Result Engine::query(std::string_view sql,ExecutionOptions execution) const {
    using Clock=std::chrono::steady_clock;auto start=execution.profile ? Clock::now():Clock::time_point{};
    auto planned=plan_query(*this,sql,execution);auto ready=execution.profile ? Clock::now():Clock::time_point{};
    auto result=execution.engine==ExecutionMode::Scalar ? execute_scalar(*this,planned):execute_vector(*this,planned);
    if(execution.profile) {auto done=Clock::now();result.planning_ns=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(ready-start).count());result.execution_ns=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(done-ready).count());}
    return result;
}
}
