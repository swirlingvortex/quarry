#include "quarry/quarry.hpp"
#include "json.hpp"
#include <fstream>
#include <unordered_set>

namespace quarry {
Column::Column(ColumnSpec s, std::pmr::memory_resource* memory)
    : values_(Ints(memory)), validity_(memory), memory_(memory), spec(std::move(s)) {
    if (spec.type == Type::Double) values_.emplace<Doubles>(memory);
    else if (spec.type == Type::Bool) values_.emplace<Bools>(memory);
    else if (spec.type == Type::String) values_.emplace<Strings>(memory);
}
std::size_t Column::size() const { return std::visit([](const auto& v) { return v.size(); }, values_); }
ColumnView Column::view() const {
    ColumnView result{spec.type, {}, {}, {}, {}, validity_};
    switch (spec.type) {
    case Type::Int64: result.integers = std::get<Ints>(values_); break;
    case Type::Double: result.doubles = std::get<Doubles>(values_); break;
    case Type::Bool: result.booleans = std::get<Bools>(values_); break;
    case Type::String: result.strings = std::get<Strings>(values_); break;
    case Type::Null: fail("INTERNAL", "untyped column view");
    }
    return result;
}
void Column::append(const Value& value) {
    if (value.type != spec.type) fail("TYPE", "column append type mismatch");
    if (value.is_null() && !spec.nullable) fail("CSV", "NULL in non-nullable column");
    auto row = size();
    if (row % 64 == 0) validity_.push_back(0);
    if (!value.is_null()) validity_[row / 64] |= std::uint64_t(1) << (row % 64);
    switch (spec.type) {
    case Type::Int64: std::get<Ints>(values_).push_back(value.is_null() ? 0 : value.integer()); break;
    case Type::Double: std::get<Doubles>(values_).push_back(value.is_null() ? 0 : value.real()); break;
    case Type::Bool: std::get<Bools>(values_).push_back(value.is_null() ? 0 : static_cast<std::uint8_t>(value.boolean())); break;
    case Type::String: std::get<Strings>(values_).emplace_back(value.is_null() ? std::string_view{} : std::string_view(value.string())); break;
    case Type::Null: fail("INTERNAL", "untyped column");
    }
}
Value Column::at(std::size_t row) const {
    if (row >= size()) fail("INTERNAL", "column row out of bounds");
    if ((validity_[row / 64] & (std::uint64_t(1) << (row % 64))) == 0) return Value::null(spec.type);
    switch (spec.type) {
    case Type::Int64: return Value::integer(std::get<Ints>(values_)[row]);
    case Type::Double: return Value::real(std::get<Doubles>(values_)[row]);
    case Type::Bool: return Value::boolean(std::get<Bools>(values_)[row] != 0);
    case Type::String: return Value::string(std::get<Strings>(values_)[row], memory_);
    case Type::Null: break;
    }
    fail("INTERNAL", "untyped column");
}
namespace {
struct Field { std::string text; bool quoted = false; };
class CsvReader {
    std::ifstream in_;
    std::string file_;
    std::size_t record_ = 0;
public:
    explicit CsvReader(const std::filesystem::path& path) : in_(path, std::ios::binary), file_(path.string()) {
        if (!in_) fail("IO", "cannot open " + file_);
    }
    [[noreturn]] void error(std::size_t column, std::string message) const {
        fail("CSV", file_ + ": record " + std::to_string(record_) + ", column " + std::to_string(column) + ": " + message);
    }
    bool next(std::vector<Field>& fields) {
        fields.clear();
        if (in_.peek() == EOF) { if (in_.bad()) fail("IO", "read failed: " + file_); return false; }
        ++record_;
        std::size_t bytes = 0;
        auto get = [&]() {
            int c = in_.get();
            if (c != EOF && ++bytes > 8 * 1024 * 1024) error(fields.size() + 1, "record exceeds 8 MiB");
            return c;
        };
        for (;;) {
            Field field;
            int c = get();
            auto append = [&](int ch) {
                if (field.text.size() >= 1024 * 1024) error(fields.size() + 1, "field exceeds 1 MiB");
                field.text.push_back(static_cast<char>(ch));
            };
            if (c == '"') {
                field.quoted = true;
                for (;;) {
                    c = get();
                    if (c == EOF) error(fields.size() + 1, "unterminated quoted field");
                    if (c == '"') {
                        c = get();
                        if (c != '"') break;
                    }
                    append(c);
                }
                if (c != ',' && c != '\n' && c != '\r' && c != EOF) error(fields.size() + 1, "characters after closing quote");
            } else {
                while (c != ',' && c != '\n' && c != '\r' && c != EOF) {
                    if (c == '"') error(fields.size() + 1, "quote in unquoted field");
                    append(c); c = get();
                }
            }
            if (!valid_utf8(field.text)) error(fields.size() + 1, "invalid UTF-8");
            fields.push_back(std::move(field));
            if (fields.size() > 4096) error(fields.size(), "too many fields");
            if (c == ',') continue;
            if (c == '\r' && get() != '\n') error(fields.size(), "bare CR record separator");
            if (in_.bad()) fail("IO", "read failed: " + file_);
            return true;
        }
    }
};
}
void Engine::load_catalog(const std::filesystem::path& manifest) {
    std::unordered_map<std::string, std::unique_ptr<Table>> pending;
    try {
        auto text = read_bounded(manifest, 1024 * 1024);
        check_json_depth(text);
        auto json = nlohmann::json::parse(text);
        if (!json.is_object() || !json.contains("tables") || !json.at("tables").is_array()) fail("CATALOG", "manifest requires a tables array");
        for (const auto& entry : json.at("tables")) {
            auto name = lower(entry.at("name").get<std::string>());
            if (!valid_identifier(name) || pending.contains(name)) fail("CATALOG", "invalid or duplicate table: " + name);
            std::filesystem::path relative(entry.at("path").get<std::string>());
            if (relative.empty() || relative.is_absolute()) fail("CATALOG", "CSV path must be relative");
            for (const auto& part : relative) if (part == "..") fail("CATALOG", "CSV path must remain within manifest directory");
            auto table = std::make_unique<Table>(memory_.get()); table->name = name;
            std::unordered_set<std::string> names;
            if (!entry.at("columns").is_array() || entry.at("columns").empty() || entry.at("columns").size() > 4096) fail("CATALOG", "columns must contain 1..4096 definitions");
            for (const auto& col : entry.at("columns")) {
                auto n = lower(col.at("name").get<std::string>());
                if (!valid_identifier(n) || !names.insert(n).second) fail("CATALOG", "invalid or duplicate column: " + n);
                table->columns.emplace_back(ColumnSpec{n, parse_type(col.at("type").get<std::string>()), col.at("nullable").get<bool>()}, memory_.get());
            }
            CsvReader reader(manifest.parent_path() / relative);
            std::vector<Field> fields;
            if (!reader.next(fields)) reader.error(1, "mandatory header missing");
            if (fields.size() != table->columns.size()) reader.error(1, "header field count mismatch");
            for (std::size_t c = 0; c < fields.size(); ++c)
                if (lower(fields[c].text) != table->columns[c].spec.name) reader.error(c + 1, "header name mismatch");
            while (reader.next(fields)) {
                if (fields.size() != table->columns.size()) reader.error(1, "record field count mismatch");
                for (std::size_t c = 0; c < fields.size(); ++c) {
                    const auto& f = fields[c]; auto& column = table->columns[c];
                    try {
                        Value value = !f.quoted && f.text == "\\N" ? Value::null(column.spec.type) : parse_cell(f.text, column.spec.type, memory_.get());
                        column.append(value);
                    } catch (const Error& e) {
                        if (e.code == "RESOURCE") throw;
                        reader.error(c + 1, column.spec.name + ": " + e.what());
                    }
                }
                ++table->row_count;
            }
            pending.emplace(name, std::move(table));
        }
    } catch (const nlohmann::json::exception& e) { fail("CATALOG", std::string("invalid manifest: ") + e.what()); }
    auto next_identity=std::make_shared<const int>(0);
    tables_.swap(pending);catalog_identity_=std::move(next_identity);
}
const Table& Engine::table(std::string_view name) const {
    auto it = tables_.find(lower(name));
    if (it == tables_.end()) fail("BIND", "unknown table: " + std::string(name));
    return *it->second;
}
}
