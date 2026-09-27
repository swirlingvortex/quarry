#include "quarry/quarry.hpp"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <limits>
#include <locale>
#include <sstream>

namespace quarry {
[[noreturn]] void fail(std::string code, std::string message) { throw Error(std::move(code), std::move(message)); }
std::string lower(std::string_view text) {
    std::string result(text);
    for (char& c : result) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + ('a' - 'A'));
    return result;
}
bool valid_identifier(std::string_view text) {
    auto alpha = [](char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; };
    if (text.empty() || !alpha(text.front())) return false;
    return std::all_of(text.begin(), text.end(), [&](char c) { return alpha(c) || (c >= '0' && c <= '9'); });
}
bool valid_utf8(std::string_view text) {
    for (std::size_t i = 0; i < text.size();) {
        auto c = static_cast<unsigned char>(text[i++]);
        if (c < 0x80) continue;
        unsigned count, code, minimum;
        if (c >= 0xc2 && c <= 0xdf) { count = 1; code = c & 0x1fU; minimum = 0x80; }
        else if (c >= 0xe0 && c <= 0xef) { count = 2; code = c & 0xfU; minimum = 0x800; }
        else if (c >= 0xf0 && c <= 0xf4) { count = 3; code = c & 7U; minimum = 0x10000; }
        else return false;
        if (text.size() - i < count) return false;
        while (count--) {
            auto next = static_cast<unsigned char>(text[i++]);
            if ((next & 0xc0U) != 0x80U) return false;
            code = (code << 6U) | (next & 0x3fU);
        }
        if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return false;
    }
    return true;
}
std::string read_bounded(const std::filesystem::path& path, std::size_t limit) {
    std::ifstream in(path, std::ios::binary);
    if (!in) fail("IO", "cannot open " + path.string());
    std::string text;
    char buffer[4096];
    while (in) {
        in.read(buffer, sizeof(buffer));
        auto count = static_cast<std::size_t>(in.gcount());
        if (count > limit - text.size()) fail("RESOURCE", "file exceeds size limit: " + path.string());
        text.append(buffer, count);
    }
    if (!in.eof()) fail("IO", "read failed: " + path.string());
    return text;
}
void check_json_depth(std::string_view text, std::size_t limit) {
    std::size_t depth = 0;
    bool quoted = false, escaped = false;
    for (char c : text) {
        if (quoted) {
            if (escaped) escaped = false;
            else if (c == '\\') escaped = true;
            else if (c == '"') quoted = false;
        } else if (c == '"') quoted = true;
        else if (c == '[' || c == '{') {
            if (++depth > limit) fail("RESOURCE", "JSON nesting exceeds " + std::to_string(limit));
        } else if ((c == ']' || c == '}') && depth > 0) --depth;
    }
}
void* Memory::do_allocate(std::size_t bytes, std::size_t alignment) {
    if(failure_after_ && *failure_after_==0) fail("RESOURCE","injected accounted allocation failure");
    if (bytes > limit_ - current_) fail("RESOURCE", "engine-accounted memory limit exceeded");
    void* ptr;
    try { ptr = std::pmr::new_delete_resource()->allocate(bytes, alignment); }
    catch (const std::bad_alloc&) { fail("RESOURCE", "allocation failed"); }
    if(failure_after_) --*failure_after_;
    current_ += bytes;
    allocated_ += bytes;
    peak_ = std::max(peak_, current_);
    return ptr;
}
void Memory::do_deallocate(void* ptr, std::size_t bytes, std::size_t alignment) {
    std::pmr::new_delete_resource()->deallocate(ptr, bytes, alignment);
    current_ -= bytes;
}
std::string type_name(Type type) {
    switch (type) {
    case Type::Int64: return "INT64";
    case Type::Double: return "DOUBLE";
    case Type::Bool: return "BOOL";
    case Type::String: return "STRING";
    case Type::Null: return "NULL";
    }
    fail("INTERNAL", "invalid type");
}
Type parse_type(std::string_view name) {
    auto n = lower(name);
    if (n == "int64") return Type::Int64;
    if (n == "double") return Type::Double;
    if (n == "bool") return Type::Bool;
    if (n == "string") return Type::String;
    fail("CATALOG", "unknown storage type: " + std::string(name));
}
Value::Value(const Value& other) : type(other.type) {
    if (std::holds_alternative<String>(other.data)) data.emplace<String>(other.string(), other.string().get_allocator());
    else data = other.data;
}
Value& Value::operator=(const Value& other) {
    if (this != &other) { Value copy(other); *this = std::move(copy); }
    return *this;
}
Value Value::null(Type t) { Value v; v.type = t; return v; }
Value Value::integer(std::int64_t n) { Value v; v.type = Type::Int64; v.data = n; return v; }
Value Value::real(double n) {
    if (!std::isfinite(n)) fail("NUMERIC", "nonfinite DOUBLE result");
    Value v; v.type = Type::Double; v.data = n; return v;
}
Value Value::boolean(bool n) { Value v; v.type = Type::Bool; v.data = n; return v; }
Value Value::string(std::string_view n, std::pmr::memory_resource* memory) {
    Value v; v.type = Type::String; v.data.emplace<String>(n, memory); return v;
}
Value numeric(std::string_view op, const Value& left, const Value& right) {
    Type out = op == "/" ? Type::Double : left.type;
    if (left.is_null() || right.is_null()) return Value::null(out);
    if (left.type != right.type || (left.type != Type::Int64 && left.type != Type::Double)) fail("TYPE", "numeric operand type mismatch");
    if (left.type == Type::Int64 && op != "/") {
        std::int64_t n = 0;
        bool overflow = op == "+" ? __builtin_add_overflow(left.integer(), right.integer(), &n)
                      : op == "-" ? __builtin_sub_overflow(left.integer(), right.integer(), &n)
                      : __builtin_mul_overflow(left.integer(), right.integer(), &n);
        if (overflow) fail("NUMERIC", "INT64 arithmetic overflow");
        return Value::integer(n);
    }
    double a = left.type == Type::Int64 ? static_cast<double>(left.integer()) : left.real();
    double b = right.type == Type::Int64 ? static_cast<double>(right.integer()) : right.real();
    if (op == "/" && b == 0) fail("NUMERIC", "division by zero");
    return Value::real(op == "+" ? a + b : op == "-" ? a - b : op == "*" ? a * b : a / b);
}
Value negate(const Value& v) {
    if (v.is_null()) return Value::null(v.type);
    if (v.type == Type::Double) return Value::real(-v.real());
    if (v.type != Type::Int64) fail("TYPE", "unary minus requires numeric input");
    if (v.integer() == std::numeric_limits<std::int64_t>::min()) fail("NUMERIC", "INT64 negation overflow");
    return Value::integer(-v.integer());
}
Value truth(std::string_view op, const Value& a, const Value& b) {
    if (op == "not") return a.is_null() ? Value::null(Type::Bool) : Value::boolean(!a.boolean());
    if (op == "and") {
        if ((!a.is_null() && !a.boolean()) || (!b.is_null() && !b.boolean())) return Value::boolean(false);
        if (a.is_null() || b.is_null()) return Value::null(Type::Bool);
        return Value::boolean(true);
    }
    if ((!a.is_null() && a.boolean()) || (!b.is_null() && b.boolean())) return Value::boolean(true);
    if (a.is_null() || b.is_null()) return Value::null(Type::Bool);
    return Value::boolean(false);
}
int compare(const Value& a, const Value& b) {
    if (a.type != b.type || a.is_null() || b.is_null()) fail("INTERNAL", "invalid comparison contract");
    switch (a.type) {
    case Type::Int64: return (a.integer() > b.integer()) - (a.integer() < b.integer());
    case Type::Double: return (a.real() > b.real()) - (a.real() < b.real());
    case Type::Bool: return static_cast<int>(a.boolean()) - static_cast<int>(b.boolean());
    case Type::String: {
        const auto& x = a.string(); const auto& y = b.string();
        auto n = std::min(x.size(), y.size());
        for (std::size_t i = 0; i < n; ++i) {
            auto l = static_cast<unsigned char>(x[i]), r = static_cast<unsigned char>(y[i]);
            if (l != r) return l < r ? -1 : 1;
        }
        return (x.size() > y.size()) - (x.size() < y.size());
    }
    case Type::Null: break;
    }
    fail("INTERNAL", "untyped comparison");
}
Value comparison(std::string_view op, const Value& a, const Value& b) {
    if (a.is_null() || b.is_null()) return Value::null(Type::Bool);
    int c = compare(a, b);
    return Value::boolean(op == "=" ? c == 0 : (op == "!=" || op == "<>") ? c != 0 : op == "<" ? c < 0 : op == "<=" ? c <= 0 : op == ">" ? c > 0 : c >= 0);
}
Value parse_cell(std::string_view token, Type type, std::pmr::memory_resource* memory) {
    if (type == Type::String) return Value::string(token, memory);
    if (type == Type::Bool) {
        if (lower(token) == "true") return Value::boolean(true);
        if (lower(token) == "false") return Value::boolean(false);
        fail("CSV", "expected true or false");
    }
    if (token.empty()) fail("CSV", "empty numeric field");
    // A leading plus is allowed; no whitespace, hexadecimal, NaN or Infinity.
    if (token.front() == '+') {
        token.remove_prefix(1);
        if (!token.empty() && (token.front() == '+' || token.front() == '-')) fail("CSV", "invalid numeric sign");
    }
    if (token.empty()) fail("CSV", "invalid numeric value");
    if (type == Type::Int64) {
        std::int64_t n;
        auto [end, ec] = std::from_chars(token.data(), token.data() + token.size(), n);
        if (ec != std::errc() || end != token.data() + token.size()) fail("CSV", "invalid or out-of-range INT64");
        return Value::integer(n);
    }
    bool digit = false;
    for (char c : token) {
        if (c >= '0' && c <= '9') digit = true;
        else if (c != '-' && c != '+' && c != '.' && c != 'e' && c != 'E') fail("CSV", "invalid DOUBLE token");
    }
    if (!digit) fail("CSV", "invalid DOUBLE token");
    double n;
    // libc++ floating from_chars requires macOS 26; classic-locale streams keep
    // this ingestion-only conversion portable to our actual macOS 15 host.
    std::istringstream stream{std::string(token)};
    stream.imbue(std::locale::classic());
    stream >> std::noskipws >> n;
    if (stream.fail() || !stream.eof() || !std::isfinite(n)) fail("CSV", "invalid or nonfinite DOUBLE");
    return Value::real(n);
}
}
