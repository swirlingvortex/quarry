#pragma once
#include "quarry/quarry.hpp"
#include <limits>
namespace quarry {
// Compiler-specific integer extension is intentionally isolated here.
class WideSum {
    __int128 value_ = 0;
public:
    void add(std::int64_t n) {
        __int128 next;
        if (__builtin_add_overflow(value_, static_cast<__int128>(n), &next)) fail("NUMERIC", "wide SUM overflow");
        value_ = next;
    }
    std::int64_t finish() const {
        if (value_ < std::numeric_limits<std::int64_t>::min() || value_ > std::numeric_limits<std::int64_t>::max())
            fail("NUMERIC", "SUM exceeds INT64 result range");
        return static_cast<std::int64_t>(value_);
    }
    double mean(std::int64_t count) const { return static_cast<double>(static_cast<long double>(value_) / count); }
};
}
