#include "sql/internal.hpp"
#include <algorithm>
#include <charconv>
#include <limits>
#include <unordered_set>

namespace quarry {
namespace {
enum class TokenKind { Word, Number, String, Symbol, End };
struct Token { TokenKind kind; std::string text; std::size_t offset; };
bool digit(char c) { return c >= '0' && c <= '9'; }
bool letter(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; }
std::vector<Token> tokenize(std::string_view sql) {
    if (sql.size() > 65536) fail("RESOURCE", "SQL exceeds 64 KiB");
    if (!valid_utf8(sql)) fail("PARSE", "SQL is not valid UTF-8");
    std::vector<Token> result;
    for (std::size_t i = 0; i < sql.size();) {
        char c = sql[i];
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { ++i; continue; }
        if (c == '-' && i + 1 < sql.size() && sql[i + 1] == '-') { while (i < sql.size() && sql[i] != '\n') ++i; continue; }
        auto start = i;
        TokenKind kind = TokenKind::Symbol;
        std::string text;
        if (letter(c)) { kind = TokenKind::Word; while (i < sql.size() && (letter(sql[i]) || digit(sql[i]))) ++i; text = lower(sql.substr(start, i - start)); }
        else if (digit(c) || (c == '.' && i + 1 < sql.size() && digit(sql[i + 1]))) {
            kind = TokenKind::Number;
            while (i < sql.size() && digit(sql[i])) ++i;
            if (i < sql.size() && sql[i] == '.') { ++i; while (i < sql.size() && digit(sql[i])) ++i; }
            if (i < sql.size() && (sql[i] == 'e' || sql[i] == 'E')) {
                ++i; if (i < sql.size() && (sql[i] == '+' || sql[i] == '-')) ++i;
                if (i == sql.size() || !digit(sql[i])) fail("PARSE", "exponent requires digits");
                while (i < sql.size() && digit(sql[i])) ++i;
            }
            text = std::string(sql.substr(start, i - start));
        } else if (c == '\'') {
            kind = TokenKind::String; ++i; bool closed = false;
            while (i < sql.size()) {
                char next = sql[i++];
                if (next == '\'') {
                    if (i < sql.size() && sql[i] == '\'') { ++i; text += '\''; }
                    else { closed = true; break; }
                } else text += next;
            }
            if (!closed) fail("PARSE", "unterminated string literal");
        } else {
            if (c == '"' || c == '`' || c == '[') fail("UNSUPPORTED", "quoted identifiers are not supported");
            if (std::string_view("(),.;+-*/=<>!").find(c) == std::string_view::npos) fail("PARSE", "invalid character at byte " + std::to_string(i));
            text += c; ++i;
            if (i < sql.size() && ((sql[i] == '=' && (c == '<' || c == '>' || c == '!')) || (c == '<' && sql[i] == '>'))) text += sql[i++];
            if (text == "!") fail("PARSE", "expected !=");
        }
        result.push_back({kind, std::move(text), start});
        if (result.size() > 4096) fail("RESOURCE", "SQL exceeds 4096 tokens");
    }
    result.push_back({TokenKind::End, "", sql.size()}); return result;
}
bool reserved(std::string_view s) {
    static const std::unordered_set<std::string> words = {"select","from","as","where","group","by","order","limit","asc","desc","nulls","first","last","and","or","not","is","null","true","false","cast","distinct","having","offset","join","inner","left","right","full","outer","cross","on","union","with","over","in","like","between"};
    return words.contains(std::string(s));
}
std::unique_ptr<Expr> node(ExprKind kind, std::string op = {}) { auto e = std::make_unique<Expr>(); e->kind = kind; e->op = std::move(op); return e; }
class Parser {
    std::vector<Token> tokens_;
    std::size_t index_ = 0, depth_ = 0;
    std::pmr::memory_resource* memory_;
    const Token& peek() const { return tokens_[index_]; }
    bool take(std::string_view s) { if (peek().kind != TokenKind::String && peek().text == s) { ++index_; return true; } return false; }
    void expect(std::string_view s) { if (!take(s)) fail("PARSE", "expected '" + std::string(s) + "' at byte " + std::to_string(peek().offset)); }
    std::string identifier() {
        if (peek().kind != TokenKind::Word || reserved(peek().text)) fail("PARSE", "expected identifier at byte " + std::to_string(peek().offset));
        return tokens_[index_++].text;
    }
    std::size_t unsigned_integer(bool positive) {
        if (peek().kind != TokenKind::Number) fail("PARSE", "expected integer");
        auto text = tokens_[index_++].text; std::size_t n;
        auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), n);
        if (ec != std::errc() || end != text.data() + text.size() || (positive && n == 0)) fail("PARSE", "invalid integer position or limit");
        return n;
    }
    std::unique_ptr<Expr> prefix() {
        if (take("not")) { auto e = node(ExprKind::Unary, "not"); e->left = expression(3); return e; }
        if (take("-")) {
            if (peek().kind == TokenKind::Number && peek().text == "9223372036854775808") {
                ++index_; auto e = node(ExprKind::Literal); e->literal = Value::integer(INT64_MIN); return e;
            }
            auto e = node(ExprKind::Unary, "-"); e->left = expression(6); return e;
        }
        if (take("(")) { auto e = expression(); expect(")"); return e; }
        if (peek().kind == TokenKind::String) { auto e = node(ExprKind::Literal); e->literal = Value::string(tokens_[index_++].text, memory_); return e; }
        if (peek().kind == TokenKind::Number) {
            auto e = node(ExprKind::Literal); auto token = tokens_[index_++].text;
            try { e->literal = parse_cell(token, token.find_first_of(".eE") == std::string::npos ? Type::Int64 : Type::Double, memory_); }
            catch (const Error&) { fail("NUMERIC", "numeric literal out of range: " + token); }
            return e;
        }
        if (take("null")) return node(ExprKind::Literal);
        if (take("true")) { auto e = node(ExprKind::Literal); e->literal = Value::boolean(true); return e; }
        if (take("false")) { auto e = node(ExprKind::Literal); e->literal = Value::boolean(false); return e; }
        if (take("cast")) {
            auto e = node(ExprKind::Cast); expect("("); e->left = expression(); expect("as");
            auto name = identifier();
            if (name == "bigint") e->type = Type::Int64;
            else if (name == "double") e->type = Type::Double;
            else if (name == "boolean") e->type = Type::Bool;
            else if (name == "varchar") e->type = Type::String;
            else fail("UNSUPPORTED", "unsupported CAST target: " + name);
            expect(")"); return e;
        }
        if (take("*")) return node(ExprKind::Star);
        auto name = identifier();
        if (take("(")) {
            if (name != "count" && name != "sum" && name != "avg" && name != "min" && name != "max") fail("UNSUPPORTED", "unsupported function: " + name);
            auto e = node(ExprKind::Aggregate, name); e->left = expression(); expect(")"); return e;
        }
        auto e = node(ExprKind::Column); e->name = name;
        if (take(".")) {
            e->qualifier = name;
            if (take("*")) e->kind = ExprKind::Star;
            else e->name = identifier();
        }
        return e;
    }
    std::unique_ptr<Expr> expression(int minimum = 1) {
        if (++depth_ > 128) fail("RESOURCE", "expression nesting exceeds 128");
        auto e = prefix();
        for (;;) {
            auto op = peek().kind == TokenKind::String ? "" : peek().text;
            int precedence = op == "or" ? 1 : op == "and" ? 2 : (op == "=" || op == "!=" || op == "<>" || op == "<" || op == "<=" || op == ">" || op == ">=" || op == "is") ? 3 : (op == "+" || op == "-") ? 4 : (op == "*" || op == "/") ? 5 : 0;
            if (precedence < minimum) break;
            ++index_;
            if (op == "is") {
                bool negated = take("not"); expect("null");
                auto parent = node(ExprKind::IsNull, negated ? "is not null" : "is null"); parent->left = std::move(e); e = std::move(parent);
            } else {
                auto parent = node(ExprKind::Binary, op); parent->left = std::move(e); parent->right = expression(precedence + 1); e = std::move(parent);
            }
        }
        --depth_; return e;
    }
public:
    Parser(std::string_view sql, std::pmr::memory_resource* memory) : tokens_(tokenize(sql)), memory_(memory) {}
    BoundQuery parse() {
        BoundQuery q;
        if (peek().text != "select") fail("UNSUPPORTED", "only SELECT statements are supported");
        expect("select"); if (take("distinct")) fail("UNSUPPORTED", "DISTINCT is not supported");
        do { SelectItem item; item.expr = expression(); if (take("as")) item.alias = identifier(); q.select.push_back(std::move(item)); } while (take(","));
        expect("from"); q.table_name = identifier(); q.alias = q.table_name;
        if (take("as")) q.alias = identifier();
        if (take("inner")) {
            expect("join");q.right_name=identifier();q.right_alias=q.right_name;
            if(take("as")) q.right_alias=identifier();
            expect("on");q.join=expression();
        }
        if (take("where")) q.where = expression();
        if (take("group")) { expect("by"); do { q.groups.push_back(expression()); } while (take(",")); }
        if (take("order")) {
            expect("by"); do {
                Order o;
                if (peek().kind == TokenKind::Number) o.position = unsigned_integer(true);
                else o.name = identifier();
                if (take("desc")) o.descending = true; else take("asc");
                if (take("nulls")) { if (take("first")) o.nulls_first = true; else expect("last"); }
                q.order.push_back(std::move(o));
            } while (take(","));
        }
        if (take("limit")) q.limit = unsigned_integer(false);
        take(";");
        if (peek().kind != TokenKind::End) fail("UNSUPPORTED", "unsupported or trailing syntax at byte " + std::to_string(peek().offset) + ": " + peek().text);
        return q;
    }
};
bool numeric_type(Type t) { return t == Type::Int64 || t == Type::Double; }
void inherit(Expr& e, Type type) {
    if (e.type != Type::Null) return;
    bool arithmetic = (e.kind == ExprKind::Unary && e.op == "-") ||
        (e.kind == ExprKind::Binary && (e.op == "+" || e.op == "-" || e.op == "*" || e.op == "/"));
    if (arithmetic && type != Type::Null && !numeric_type(type)) fail("TYPE", "numeric NULL expression requires numeric context");
    e.type = type;
    if (e.kind == ExprKind::Literal) e.literal.type = type;
    else if (e.kind == ExprKind::Unary && e.op == "-") inherit(*e.left, type);
    else if (e.kind == ExprKind::Binary && (e.op == "+" || e.op == "-" || e.op == "*" || e.op == "/")) { inherit(*e.left, type); inherit(*e.right, type); }
}
void validate_inferred_types(const Expr& e) {
    if ((e.kind == ExprKind::Unary && e.op == "-") ||
        (e.kind == ExprKind::Binary && (e.op == "+" || e.op == "-" || e.op == "*" || e.op == "/"))) {
        if (!numeric_type(e.left->type)) fail("TYPE", "ambiguous or nonnumeric arithmetic operand");
        if (e.right && e.left->type != e.right->type) fail("TYPE", "arithmetic requires matching numeric operands");
        if (e.type != (e.op == "/" ? Type::Double : e.left->type)) fail("TYPE", "invalid inferred arithmetic result");
    }
    if (e.left) validate_inferred_types(*e.left);
    if (e.right) validate_inferred_types(*e.right);
}
std::string label(const Expr& e) {
    switch (e.kind) {
    case ExprKind::Column: return e.name;
    case ExprKind::Star: return "*";
    case ExprKind::Aggregate: return e.op + "(" + label(*e.left) + ")";
    case ExprKind::Literal:
        if (e.literal.is_null()) return "null";
        if (e.literal.type == Type::Int64) return std::to_string(e.literal.integer());
        if (e.literal.type == Type::Double) return std::to_string(e.literal.real());
        if (e.literal.type == Type::Bool) return e.literal.boolean() ? "true" : "false";
        return std::string(e.literal.string());
    case ExprKind::Unary: return e.op + "(" + label(*e.left) + ")";
    case ExprKind::Binary: return "(" + label(*e.left) + " " + e.op + " " + label(*e.right) + ")";
    case ExprKind::IsNull: return label(*e.left) + " " + e.op;
    case ExprKind::Cast: return "cast(" + label(*e.left) + " as " + type_name(e.type) + ")";
    }
    fail("INTERNAL", "invalid expression kind");
}
class Binder {
    BoundQuery& q_;
    bool valid_qualifier(std::string_view name) const { return name.empty() || name == q_.alias || (q_.right_table && name==q_.right_alias); }
    Type bind(Expr& e, bool inside_aggregate = false, std::size_t depth = 0) {
        if (depth >= 128) fail("RESOURCE", "expression tree depth exceeds 128");
        if (e.kind == ExprKind::Literal) return e.type = e.literal.type;
        if (e.kind == ExprKind::Column) {
            if (!valid_qualifier(e.qualifier)) fail("BIND", "unknown table qualifier: " + e.qualifier);
            std::size_t matches=0;
            for(std::size_t i=0;i<q_.columns.size();++i) {
                const auto& column=q_.columns[i];
                if(column.column->spec.name==e.name && (e.qualifier.empty() || e.qualifier==column.qualifier)) {e.column=i;e.type=column.column->spec.type;++matches;}
            }
            if(matches!=1) fail("BIND",matches ? "ambiguous column: "+e.name : "unknown column: "+e.name);
            return e.type;
        }
        if (e.kind == ExprKind::Star) fail("BIND", "star is only allowed in SELECT list or COUNT(*)");
        if (e.kind == ExprKind::Aggregate) {
            if (inside_aggregate) fail("BIND", "nested aggregate");
            if (e.left->kind == ExprKind::Star) {
                if (e.op != "count" || !e.left->qualifier.empty()) fail("BIND", "only COUNT(*) accepts star");
                e.type = Type::Int64;
            } else {
                auto t = bind(*e.left, true, depth + 1);
                if (e.op == "count") e.type = Type::Int64;
                else {
                    if (t == Type::Null) fail("TYPE", "aggregate argument type is ambiguous");
                    if ((e.op == "sum" || e.op == "avg") && !numeric_type(t)) fail("TYPE", "SUM/AVG require numeric input");
                    e.type = e.op == "avg" ? Type::Double : t;
                }
            }
            e.aggregate = q_.aggregates.size(); q_.aggregates.push_back(&e); return e.type;
        }
        auto left = bind(*e.left, inside_aggregate, depth + 1);
        if (e.kind == ExprKind::Cast) {
            if (e.left->kind == ExprKind::Literal && e.left->literal.is_null()) { inherit(*e.left, e.type); return e.type; }
            if (left != Type::Int64 || e.type != Type::Double) fail("TYPE", "only INT64 to DOUBLE and literal NULL casts are supported");
            return e.type;
        }
        if (e.kind == ExprKind::IsNull) return e.type = Type::Bool;
        if (e.kind == ExprKind::Unary) {
            if (e.op == "not") { inherit(*e.left, Type::Bool); if (e.left->type != Type::Bool) fail("TYPE", "NOT requires BOOL"); return e.type = Type::Bool; }
            if (left != Type::Null && !numeric_type(left)) fail("TYPE", "unary minus requires numeric input");
            return e.type = left;
        }
        auto right = bind(*e.right, inside_aggregate, depth + 1);
        if (e.op == "and" || e.op == "or") {
            inherit(*e.left, Type::Bool); inherit(*e.right, Type::Bool);
            if (e.left->type != Type::Bool || e.right->type != Type::Bool) fail("TYPE", "boolean operators require BOOL");
            return e.type = Type::Bool;
        }
        inherit(*e.left, right); inherit(*e.right, left);
        left = e.left->type; right = e.right->type;
        if (left != right) fail("TYPE", "operands require matching types; use explicit INT64 to DOUBLE CAST");
        if (e.op == "+" || e.op == "-" || e.op == "*" || e.op == "/") {
            if (left != Type::Null && !numeric_type(left)) fail("TYPE", "arithmetic requires numeric inputs");
            return e.type = e.op == "/" ? Type::Double : left;
        }
        // NULL = NULL has an unambiguous BOOL output with UNKNOWN value.
        return e.type = Type::Bool;
    }
    void validate_where(const Expr& e) {
        if (e.kind == ExprKind::Aggregate || e.kind == ExprKind::Cast || e.kind == ExprKind::Star) fail("UNSUPPORTED", "aggregate, CAST or star in WHERE");
        if (e.kind == ExprKind::Binary && (e.op == "+" || e.op == "-" || e.op == "*" || e.op == "/")) fail("UNSUPPORTED", "arithmetic in WHERE");
        if (e.kind == ExprKind::Unary && e.op == "-" && (e.left->kind != ExprKind::Literal || e.left->literal.is_null())) fail("UNSUPPORTED", "arithmetic in WHERE");
        if (e.kind == ExprKind::Binary && e.op != "and" && e.op != "or") {
            auto simple = [](const Expr& v) {
                return v.kind == ExprKind::Column || v.kind == ExprKind::Literal ||
                    (v.kind == ExprKind::Unary && v.op == "-" && v.left->kind == ExprKind::Literal);
            };
            if (!simple(*e.left) || !simple(*e.right)) fail("UNSUPPORTED", "WHERE comparisons require column or literal operands");
        }
        if (e.left) validate_where(*e.left);
        if (e.right) validate_where(*e.right);
    }
    void join_keys(const Expr& e) {
        if(e.kind==ExprKind::Binary && e.op=="and") {join_keys(*e.left);join_keys(*e.right);return;}
        if(e.kind!=ExprKind::Binary || e.op!="=" || e.left->kind!=ExprKind::Column || e.right->kind!=ExprKind::Column) fail("UNSUPPORTED","JOIN ON requires conjunctions of column equalities");
        auto left=e.left->column,right=e.right->column;
        if(q_.columns[left].source==q_.columns[right].source) fail("BIND","join equality must connect opposite inputs");
        if(e.left->type==Type::Double) fail("TYPE","DOUBLE join keys are excluded");
        if(q_.columns[left].source==1) std::swap(left,right);
        q_.join_keys.emplace_back(left,right);
    }
    void grouped(const Expr& e) {
        if (e.kind == ExprKind::Aggregate) return;
        if (e.kind == ExprKind::Column && std::none_of(q_.groups.begin(), q_.groups.end(), [&](const auto& g) { return g->column == e.column; })) fail("BIND", "nonaggregate column must be grouped: " + e.name);
        if (e.left) grouped(*e.left);
        if (e.right) grouped(*e.right);
    }
public:
    explicit Binder(BoundQuery& q) : q_(q) {}
    void run() {
        if(q_.right_table && q_.alias==q_.right_alias) fail("BIND","join inputs require distinct aliases");
        if(q_.join) {bind(*q_.join);join_keys(*q_.join);}
        std::vector<SelectItem> expanded;
        for (auto& item : q_.select) {
            if (item.expr->kind != ExprKind::Star) { expanded.push_back(std::move(item)); continue; }
            if (!item.alias.empty() || !valid_qualifier(item.expr->qualifier)) fail("BIND", "invalid star alias or qualifier");
            for(const auto& column:q_.columns) {
                if(!item.expr->qualifier.empty() && item.expr->qualifier!=column.qualifier) continue;
                auto e=node(ExprKind::Column);e->name=column.column->spec.name;e->qualifier=column.qualifier;expanded.push_back({std::move(e),{}});
            }
        }
        q_.select = std::move(expanded);
        if (q_.where) {
            bind(*q_.where); validate_where(*q_.where); inherit(*q_.where, Type::Bool);
            if (q_.where->type != Type::Bool) fail("TYPE", "WHERE requires BOOL");
            validate_inferred_types(*q_.where);
        }
        for (auto& g : q_.groups) {
            if (g->kind != ExprKind::Column) fail("BIND", "GROUP BY requires column references");
            if (bind(*g) == Type::Double) fail("TYPE", "DOUBLE group keys are excluded");
        }
        for (auto& item : q_.select) {
            bind(*item.expr);
            if (item.expr->type == Type::Null) fail("TYPE", "ambiguous NULL output; use CAST");
            validate_inferred_types(*item.expr);
            q_.output.push_back({item.alias.empty() ? label(*item.expr) : item.alias, item.expr->type});
        }
        q_.aggregation = !q_.aggregates.empty() || !q_.groups.empty();
        if (q_.aggregation) for (const auto& item : q_.select) grouped(*item.expr);
        for (auto& order : q_.order) {
            if (order.position) {
                if (*order.position > q_.select.size()) fail("BIND", "ORDER BY position out of range");
                order.column = *order.position - 1;
            } else {
                std::size_t matches = 0;
                for (std::size_t i = 0; i < q_.output.size(); ++i) if (q_.output[i].name == order.name) { order.column = i; ++matches; }
                if (matches != 1) fail("BIND", "unknown or ambiguous ORDER BY output name: " + order.name);
            }
        }
    }
};
}
BoundQuery bind_query(const Engine& engine, std::string_view sql) {
    auto q=Parser(sql,engine.memory().get()).parse();q.table=&engine.table(q.table_name);
    for(const auto& column:q.table->columns) q.columns.push_back({&column,0,q.alias});
    if(!q.right_name.empty()) {
        q.right_table=&engine.table(q.right_name);
        for(const auto& column:q.right_table->columns) q.columns.push_back({&column,1,q.right_alias});
    }
    Binder(q).run();return q;
}
std::string expression_label(const Expr& expr) { return label(expr); }
bool potentially_failing(const Expr& expr) {
    if(expr.kind==ExprKind::Binary && (expr.op=="+" || expr.op=="-" || expr.op=="*" || expr.op=="/")) return true;
    if(expr.kind==ExprKind::Unary && expr.op=="-") {
        if(expr.left->kind!=ExprKind::Literal) return true;
        if(!expr.left->literal.is_null() && expr.left->type==Type::Int64 && expr.left->literal.integer()==INT64_MIN) return true;
    }
    return (expr.left && potentially_failing(*expr.left)) || (expr.right && potentially_failing(*expr.right));
}
std::string join_swap_block_reason(const BoundQuery& query) {
    for(const auto* aggregate:query.aggregates) if((aggregate->op=="sum" || aggregate->op=="avg") && aggregate->left->type==Type::Double)
        return "DOUBLE SUM/AVG accumulation order requires right build";
    if(query.where && potentially_failing(*query.where)) return "potentially failing WHERE expression requires original capped evaluation order";
    for(const auto& item:query.select) if(potentially_failing(*item.expr)) return "potentially failing projection or aggregate argument requires original capped evaluation order";
    return {};
}
}
