#pragma once
#include "sql/internal.hpp"
#include <numeric>
namespace quarry {
// Dense expression vectors own typed buffers. String views borrow immutable
// catalog/AST or completed group state, never a reused CSV or batch buffer.
struct Vector {
    Type type;
    using Ints = std::pmr::vector<std::int64_t>;
    using Doubles = std::pmr::vector<double>;
    using Bools = std::pmr::vector<std::uint8_t>;
    using Strings = std::pmr::vector<std::string_view>;
    std::variant<Ints,Doubles,Bools,Strings> data;
    std::pmr::vector<std::uint8_t> valid, faults;
    Vector(Type t, std::size_t size, std::pmr::memory_resource* memory) : type(t), data(Ints(memory)), valid(size,0,memory), faults(size,0,memory) {
        switch(t) {
        case Type::Int64: case Type::Null: std::get<Ints>(data).resize(size); break;
        case Type::Double: data.emplace<Doubles>(size,0.0,memory); break;
        case Type::Bool: data.emplace<Bools>(size,0,memory); break;
        case Type::String: data.emplace<Strings>(size,std::string_view{},memory); break;
        }
    }
    template<class T> auto& values() { return std::get<std::pmr::vector<T>>(data); }
    template<class T> const auto& values() const { return std::get<std::pmr::vector<T>>(data); }
    std::size_t size() const { return valid.size(); }
    void append(const Vector& other) {
        if (type != other.type) fail("INTERNAL","vector append type mismatch");
        std::visit([&](auto& values) { const auto& source = std::get<std::decay_t<decltype(values)>>(other.data); values.insert(values.end(),source.begin(),source.end()); },data);
        valid.insert(valid.end(),other.valid.begin(),other.valid.end());
        faults.insert(faults.end(),other.faults.begin(),other.faults.end());
    }
    void throw_if_fault(std::size_t row) const {
        static const char* messages[]={"", "INT64 arithmetic overflow", "division by zero", "nonfinite DOUBLE result", "INT64 negation overflow", "SUM exceeds INT64 result range"};
        if(faults[row]) fail("NUMERIC",messages[faults[row]]);
    }
    Value box(std::size_t row, std::pmr::memory_resource* memory) const {
        if (!valid[row]) return Value::null(type);
        switch(type) {
        case Type::Int64: return Value::integer(values<std::int64_t>()[row]);
        case Type::Double: return Value::real(values<double>()[row]);
        case Type::Bool: return Value::boolean(values<std::uint8_t>()[row]!=0);
        case Type::String: return Value::string(values<std::string_view>()[row],memory);
        case Type::Null: return Value::null(type);
        }
        fail("INTERNAL","invalid vector type");
    }
    int compare_at(std::size_t a,std::size_t b) const {
        return std::visit([&](const auto& values) { return int(values[a]>values[b])-int(values[a]<values[b]); },data);
    }
};
struct Batch {
    std::size_t row_count = 0;
    std::pmr::vector<RowRef> rows;
    std::pmr::vector<std::size_t> selection;
    explicit Batch(std::pmr::memory_resource* memory) : rows(memory), selection(memory) {}
    void reset(std::size_t offset,std::size_t count) {
        row_count=count; rows.resize(count); selection.resize(count);
        for(std::size_t i=0;i<count;++i) rows[i]=RowRef(offset+i); std::iota(selection.begin(),selection.end(),0);
    }
};
class BatchScan {
    std::size_t next_=0, count_, batch_size_;
public:
    BatchScan(std::size_t count,std::size_t batch_size) : count_(count),batch_size_(batch_size) {}
    bool next(Batch& batch) {
        if(next_==count_) return false; // EOF is separate from empty selection.
        auto count=std::min(batch_size_,count_-next_); batch.reset(next_,count);next_+=count;return true;
    }
};
Vector evaluate_batch(const Expr& expr,const std::pmr::vector<ColumnView>& columns,
                      const Batch& batch,std::pmr::memory_resource* memory,
                      const std::pmr::vector<Vector>* aggregates=nullptr);
}
