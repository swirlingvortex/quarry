#pragma once
#include "execution/common/aggregate.hpp"
#include "execution/common/runtime.hpp"
#include <functional>
#include <unordered_map>
namespace quarry {
// Source filling is provided independently by the scalar and typed batch paths.
// Each source owns at most one batch of row references, never a filtered table.
class SourceStream {
    std::pmr::vector<std::size_t> rows_;
    std::size_t offset_=0;
public:
    using Fill=std::function<bool(std::pmr::vector<std::size_t>&)>;
    Fill fill;
    SourceStream(std::pmr::memory_resource* memory,Fill callback):rows_(memory),fill(std::move(callback)) {}
    bool next(std::size_t& row) {
        while(offset_==rows_.size()) {rows_.clear();offset_=0;if(!fill(rows_)) return false;}
        row=rows_[offset_++];return true;
    }
};
class HashJoinCursor {
    const BoundQuery& query_;Runtime& runtime_;std::pmr::memory_resource* memory_;bool build_left_;
    SourceStream& left_;SourceStream& right_;
    using Matches=std::pmr::vector<std::size_t>;
    std::pmr::unordered_map<Row,Matches,KeyHash,KeyEqual> hash_;
    const Matches* matches_=nullptr;
    std::size_t active_probe_=0,match_offset_=0,candidates_=0;
    Row key(std::size_t source,std::size_t row) const {
        Row result(memory_);result.reserve(query_.join_keys.size());
        for(const auto& pair:query_.join_keys) {
            auto value=read_column(query_,source==0 ? pair.first:pair.second,RowRef(row,row));
            if(value.is_null()) {result.clear();return result;}result.push_back(std::move(value));
        }
        return result;
    }
    bool find_probe() {
        auto& source=build_left_ ? right_:left_;
        auto& stats=runtime_.get(StageKind::InnerHashJoin);
        while(source.next(active_probe_)) {
            ++stats.probe_rows;++stats.input_rows;auto probe_key=key(build_left_ ? 1:0,active_probe_);
            if(probe_key.empty()) continue;auto found=hash_.find(probe_key);if(found==hash_.end()) continue;
            matches_=&found->second;match_offset_=0;return true;
        }
        return false;
    }
    RowRef pair(std::size_t build_row) const {return build_left_ ? RowRef(build_row,active_probe_):RowRef(active_probe_,build_row);}
public:
    HashJoinCursor(const BoundQuery& query,BuildSide side,Runtime& runtime,SourceStream& left,SourceStream& right)
        : query_(query),runtime_(runtime),memory_(runtime.memory),build_left_(side==BuildSide::Left),left_(left),right_(right),hash_(memory_) {
        if(!query_.right_table) return;
        auto& stats=runtime_.get(StageKind::InnerHashJoin);Runtime::Scope scope(runtime_,stats);
        auto& source=build_left_ ? left_:right_;std::size_t row;
        while(source.next(row)) {
            ++stats.build_rows;++stats.input_rows;auto build_key=key(build_left_ ? 0:1,row);if(build_key.empty()) continue;
            auto [entry,inserted]=hash_.try_emplace(std::move(build_key));(void)inserted;entry->second.push_back(row);
        }
    }
    bool next(RowRef& row) {
        if(!query_.right_table) {std::size_t index;if(!left_.next(index)) return false;row=RowRef(index);return true;}
        auto& stats=runtime_.get(StageKind::InnerHashJoin);Runtime::Scope scope(runtime_,stats);
        if(!matches_ || match_offset_==matches_->size()) {matches_=nullptr;if(!find_probe()) return false;}
        row=pair((*matches_)[match_offset_++]);++candidates_;++stats.output_rows;++stats.candidate_rows;++stats.batches;return true;
    }
    bool next_batch(std::pmr::vector<RowRef>& rows,std::size_t size) {
        rows.clear();
        if(!query_.right_table) {
            std::size_t row;while(rows.size()<size && left_.next(row)) rows.emplace_back(row);return !rows.empty();
        }
        auto& stats=runtime_.get(StageKind::InnerHashJoin);Runtime::Scope scope(runtime_,stats);
        while(rows.size()<size) {
            if(!matches_ || match_offset_==matches_->size()) {matches_=nullptr;if(!find_probe()) break;}
            auto count=std::min(size-rows.size(),matches_->size()-match_offset_);
            for(std::size_t i=0;i<count;++i) rows.push_back(pair((*matches_)[match_offset_++]));
        }
        candidates_+=rows.size();stats.output_rows+=rows.size();stats.candidate_rows+=rows.size();if(!rows.empty()) ++stats.batches;
        return !rows.empty();
    }
};
}
