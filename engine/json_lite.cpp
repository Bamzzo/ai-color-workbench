#include "json_lite.h"

#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace jsonlite {
namespace {

class Scanner {
public:
    explicit Scanner(const std::string& s) : s_(s) {}

    bool parseObject(Object& out, std::string& error) {
        skipWs();
        if (!consume('{')) return fail(error, "expected '{'");
        skipWs();
        if (consume('}')) {
            skipWs();
            return atEnd(error);
        }
        for (;;) {
            skipWs();
            std::string key;
            if (!parseString(key, error)) return false;
            skipWs();
            if (!consume(':')) return fail(error, "expected ':'");
            skipWs();
            if (out.count >= 24) return fail(error, "too many keys");
            for (int i = 0; i < out.count; ++i) {
                if (out.keys[i] == key) return fail(error, "duplicate key: " + key);
            }
            Value v;
            if (!parseValue(v, error)) return false;
            out.keys[out.count] = key;
            out.values[out.count] = v;
            ++out.count;
            skipWs();
            if (consume(',')) continue;
            if (consume('}')) break;
            return fail(error, "expected ',' or '}'");
        }
        skipWs();
        return atEnd(error);
    }

private:
    bool atEnd(std::string& error) {
        if (i_ != s_.size()) return fail(error, "trailing data after object");
        return true;
    }

    bool fail(std::string& error, const std::string& msg) {
        error = msg + " at offset " + std::to_string(i_);
        return false;
    }

    void skipWs() {
        while (i_ < s_.size()) {
            char c = s_[i_];
            if (c == ' ' || c == '\t' || c == '\r' || c == '\n') {
                ++i_;
            } else {
                break;
            }
        }
    }

    bool consume(char c) {
        if (i_ < s_.size() && s_[i_] == c) {
            ++i_;
            return true;
        }
        return false;
    }

    bool parseValue(Value& v, std::string& error) {
        if (i_ >= s_.size()) return fail(error, "unexpected end");
        char c = s_[i_];
        if (c == '"') {
            v.type = Value::Type::String;
            return parseString(v.text, error);
        }
        if (c == 't') {
            if (!literal("true")) return fail(error, "invalid literal");
            v.type = Value::Type::Bool;
            v.boolean = true;
            return true;
        }
        if (c == 'f') {
            if (!literal("false")) return fail(error, "invalid literal");
            v.type = Value::Type::Bool;
            v.boolean = false;
            return true;
        }
        if (c == 'n') {
            if (!literal("null")) return fail(error, "invalid literal");
            v.type = Value::Type::Null;
            return true;
        }
        if (c == '-' || (c >= '0' && c <= '9')) {
            v.type = Value::Type::Number;
            return parseNumber(v.number, error);
        }
        return fail(error, "unsupported value");
    }

    bool literal(const char* text) {
        size_t n = std::strlen(text);
        if (s_.compare(i_, n, text) != 0) return false;
        i_ += n;
        return true;
    }

    bool parseNumber(double& out, std::string& error) {
        size_t start = i_;
        if (i_ < s_.size() && s_[i_] == '-') ++i_;
        if (i_ >= s_.size() || s_[i_] < '0' || s_[i_] > '9') {
            return fail(error, "invalid number");
        }
        if (s_[i_] == '0') {
            ++i_;
        } else {
            while (i_ < s_.size() && s_[i_] >= '0' && s_[i_] <= '9') ++i_;
        }
        if (i_ < s_.size() && s_[i_] == '.') {
            ++i_;
            if (i_ >= s_.size() || s_[i_] < '0' || s_[i_] > '9') {
                return fail(error, "invalid fraction");
            }
            while (i_ < s_.size() && s_[i_] >= '0' && s_[i_] <= '9') ++i_;
        }
        if (i_ < s_.size() && (s_[i_] == 'e' || s_[i_] == 'E')) {
            ++i_;
            if (i_ < s_.size() && (s_[i_] == '+' || s_[i_] == '-')) ++i_;
            if (i_ >= s_.size() || s_[i_] < '0' || s_[i_] > '9') {
                return fail(error, "invalid exponent");
            }
            while (i_ < s_.size() && s_[i_] >= '0' && s_[i_] <= '9') ++i_;
        }
        std::string token = s_.substr(start, i_ - start);
        char* end = nullptr;
        errno = 0;
        double value = std::strtod(token.c_str(), &end);
        if (end == nullptr || *end != '\0' || errno == ERANGE ||
            !std::isfinite(value)) {
            return fail(error, "number out of range");
        }
        out = value;
        return true;
    }

    static void appendUtf8(std::string& out, unsigned cp) {
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else if (cp < 0x10000) {
            out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        }
    }

    bool hex4(unsigned& out) {
        if (i_ + 4 > s_.size()) return false;
        out = 0;
        for (int k = 0; k < 4; ++k) {
            char c = s_[i_++];
            out <<= 4;
            if (c >= '0' && c <= '9') {
                out |= static_cast<unsigned>(c - '0');
            } else if (c >= 'a' && c <= 'f') {
                out |= static_cast<unsigned>(c - 'a' + 10);
            } else if (c >= 'A' && c <= 'F') {
                out |= static_cast<unsigned>(c - 'A' + 10);
            } else {
                return false;
            }
        }
        return true;
    }

    bool parseString(std::string& out, std::string& error) {
        if (!consume('"')) return fail(error, "expected string");
        out.clear();
        while (i_ < s_.size()) {
            unsigned char c = static_cast<unsigned char>(s_[i_++]);
            if (c == '"') return true;
            if (c < 0x20) return fail(error, "control character in string");
            if (c != '\\') {
                out.push_back(static_cast<char>(c));
                continue;
            }
            if (i_ >= s_.size()) return fail(error, "truncated escape");
            char e = s_[i_++];
            switch (e) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                case 'u': {
                    unsigned cp = 0;
                    if (!hex4(cp)) return fail(error, "invalid \\u escape");
                    if (cp >= 0xD800 && cp <= 0xDBFF) {
                        if (i_ + 1 >= s_.size() || s_[i_] != '\\' ||
                            s_[i_ + 1] != 'u') {
                            return fail(error, "unpaired high surrogate");
                        }
                        i_ += 2;
                        unsigned low = 0;
                        if (!hex4(low) || low < 0xDC00 || low > 0xDFFF) {
                            return fail(error, "invalid low surrogate");
                        }
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                    } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                        return fail(error, "unpaired low surrogate");
                    }
                    appendUtf8(out, cp);
                    break;
                }
                default:
                    return fail(error, "invalid escape");
            }
        }
        return fail(error, "unterminated string");
    }

    const std::string& s_;
    size_t i_ = 0;
};

}  // namespace

const Value* Object::find(const std::string& key) const {
    for (int i = 0; i < count; ++i) {
        if (keys[i] == key) return &values[i];
    }
    return nullptr;
}

bool parseObject(const std::string& text, Object& out, std::string& error) {
    out = Object{};
    Scanner scanner(text);
    return scanner.parseObject(out, error);
}

std::string escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out.push_back(static_cast<char>(c));
                }
        }
    }
    return out;
}

}  // namespace jsonlite
