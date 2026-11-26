#pragma once

#include <string>

namespace jsonlite {

// Strict, minimal JSON support for the worker request. The request is a flat
// object of strings / numbers / booleans / null. Duplicate keys, trailing
// tokens, NaN/Infinity and malformed escapes are rejected. This keeps the
// engine free of an external JSON dependency while still failing loudly.
struct Value {
    enum class Type { Null, Bool, Number, String };
    Type type = Type::Null;
    bool boolean = false;
    double number = 0.0;
    std::string text;
};

struct Object {
    std::string keys[24];
    Value values[24];
    int count = 0;

    const Value* find(const std::string& key) const;
};

// Parses exactly one object and rejects anything after it.
// Returns false and fills `error` on failure. Object must be shallow (no
// nested arrays/objects) because the protocol does not use them.
bool parseObject(const std::string& text, Object& out, std::string& error);

// Escapes a UTF-8 string for inclusion in a JSON document.
std::string escape(const std::string& s);

}  // namespace jsonlite
