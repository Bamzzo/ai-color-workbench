// ============================================================================
// 【文件总体作用】
//   Iridas / Adobe .cube 三维查找表的读写器。渲染引擎不直接打开文本，
//   而是先经本文件解析成 CubeLut：边长、Domain、以及按“R 最快、B 最慢”排好的浮点采样。
//   写出函数只供测试和自检；正式导出 LUT 的路径在 Python 侧。
//
// 【输入与输出】
//   输入：.cube 文本路径，或内存中的 CubeLut。
//   输出：CubeLut（size、domain_min/max、title、samples），失败时带错误种类与行号说明。
//
// 【核心算法要点】
//   严格子集解析：只接受 3D LUT，拒绝 1D、重复头、数据后再出现关键字。
//   采样值限制在 ±65504（float16 最大有限值量级），防止异常文件把 GPU 纹理撑出 Inf。
//   数据布局 index = 3 * (r + N * (g + N * b))，与 glTexImage3D 的 RGB 紧密排列一致。
// ============================================================================
#include "cube.h"

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

namespace {

// 单文件上限 32 MiB。正常 65³ 的 .cube 远小于此，超过即视为不受支持，避免一次读爆内存。
constexpr std::uintmax_t kMaxCubeBytes = 32ull * 1024ull * 1024ull;
// 单个采样绝对值上限，约等于 IEEE 半精度浮点的最大有限值 65504。
constexpr float kMaxAbsSample = 65504.0f;

bool isBlank(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

// 去掉首尾空白。解析前每行都会走一遍，使关键字识别不依赖缩进。
std::string trim(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && isBlank(s[a])) ++a;
    while (b > a && isBlank(s[b - 1])) --b;
    return s.substr(a, b - a);
}

// 把一个词解析成有限浮点。applySampleLimit 为真时拒绝超出 kMaxAbsSample 的采样。
bool parseFinite(const std::string& token, float& out, bool applySampleLimit) {
    if (token.empty()) return false;
    char* end = nullptr;
    errno = 0;
    // strtod 要求整段都被消费（*end == '\0'），拒绝 "1.0abc" 这类夹带字符的词。
    double v = std::strtod(token.c_str(), &end);
    if (end == nullptr || *end != '\0' || errno == ERANGE || !std::isfinite(v)) {
        return false;
    }
    if (applySampleLimit && std::fabs(v) > static_cast<double>(kMaxAbsSample)) {
        return false;
    }
    out = static_cast<float>(v);
    return true;
}

// 按空白把一行切成词。数据行必须正好得到 3 个词（R G B）。
std::vector<std::string> tokenize(const std::string& s) {
    std::vector<std::string> out;
    size_t i = 0;
    while (i < s.size()) {
        while (i < s.size() && isBlank(s[i])) ++i;
        if (i >= s.size()) break;
        size_t start = i;
        while (i < s.size() && !isBlank(s[i])) ++i;
        out.push_back(s.substr(start, i - start));
    }
    return out;
}

// 去掉 '#' 注释。普通行从第一个 '#' 截断；
// TITLE 行里引号内部的 '#' 属于标题文字，不能当成注释。
std::string stripComment(const std::string& line, bool titleLine) {
    if (!titleLine) {
        auto p = line.find('#');
        return p == std::string::npos ? line : line.substr(0, p);
    }
    bool inQuote = false;
    for (size_t i = 0; i < line.size(); ++i) {
        char c = line[i];
        if (c == '"') inQuote = !inQuote;
        if (c == '#' && !inQuote) return line.substr(0, i);
    }
    return line;
}

// 本解析器认识的头关键字。其中 1D 与 INPUT_RANGE 会被明确拒绝，而不是悄悄忽略。
bool isHeaderKey(const std::string& key) {
    return key == "TITLE" || key == "LUT_3D_SIZE" || key == "DOMAIN_MIN" ||
           key == "DOMAIN_MAX" || key == "LUT_1D_SIZE" ||
           key == "LUT_1D_INPUT_RANGE" || key == "LUT_3D_INPUT_RANGE" ||
           key == "INPUT_RANGE";
}

bool fail(CubeError& error, CubeErrorKind kind, const std::string& message) {
    error.kind = kind;
    error.message = message;
    return false;
}

}  // namespace

// 【模块功能】把 .cube 文件解析为 CubeLut。
// 【关键参数】path 为文件系统路径；out 在失败时会被清空成默认对象。
// 【数据顺序】采样按蓝轴最慢、红轴最快写入 samples，每格连续 3 个 float：R、G、B。
bool loadCubeFile(const std::string& path, CubeLut& out, CubeError& error) {
    out = CubeLut{};
    error = CubeError{};

    std::error_code ec;
    std::uintmax_t fileSize = std::filesystem::file_size(path, ec);
    if (ec) return fail(error, CubeErrorKind::Io, "cannot stat LUT file");
    if (fileSize > kMaxCubeBytes) {
        return fail(error, CubeErrorKind::Unsupported, "LUT file exceeds 32 MiB");
    }

    std::ifstream f(std::filesystem::path(path), std::ios::binary);
    if (!f) return fail(error, CubeErrorKind::Io, "cannot open LUT file");
    std::string content((std::istreambuf_iterator<char>(f)),
                        std::istreambuf_iterator<char>());
    if (!f.good() && !f.eof()) {
        return fail(error, CubeErrorKind::Io, "cannot read LUT file");
    }

    // 去掉 UTF-8 BOM（EF BB BF）。带 BOM 的 TITLE 行否则会认不出关键字。
    if (content.size() >= 3 && static_cast<unsigned char>(content[0]) == 0xEF &&
        static_cast<unsigned char>(content[1]) == 0xBB &&
        static_cast<unsigned char>(content[2]) == 0xBF) {
        content.erase(0, 3);
    }

    bool sawSize = false;
    bool sawMin = false;
    bool sawMax = false;
    bool sawTitle = false;
    bool sawData = false;
    std::size_t expectedSamples = 0;  // N³ × 3 个 float
    std::size_t dataLines = 0;

    std::istringstream stream(content);
    std::string raw;
    int lineNo = 0;
    while (std::getline(stream, raw)) {
        ++lineNo;
        if (!raw.empty() && raw.back() == '\r') raw.pop_back();

        std::string trimmed = trim(raw);
        if (trimmed.empty()) continue;

        // TITLE 可能含引号内的 '#'，先判断是不是标题行，再决定注释规则。
        bool titleLine = trimmed.rfind("TITLE", 0) == 0;
        std::string line = trim(stripComment(raw, titleLine));
        if (line.empty()) continue;

        std::vector<std::string> tok = tokenize(line);
        if (tok.empty()) continue;
        const std::string& key = tok[0];

        // 数据行正好是三个有限数。一旦出现过数据，再遇到头关键字就是错误，
        // 不允许“写一段数据、回头再改 Domain”这种含糊文件。
        bool looksHeader = isHeaderKey(key);
        if (sawData || !looksHeader) {
            if (looksHeader) {
                return fail(error, CubeErrorKind::Parse,
                            "header after data at line " +
                                std::to_string(lineNo));
            }
            float firstValue = 0.0f;
            if (!parseFinite(key, firstValue, false)) {
                return fail(error, CubeErrorKind::Unsupported,
                            "unknown .cube keyword: " + key);
            }
            if (!sawSize) {
                return fail(error, CubeErrorKind::Parse,
                            "data before LUT_3D_SIZE at line " +
                                std::to_string(lineNo));
            }
            sawData = true;
            if (tok.size() != 3) {
                return fail(error, CubeErrorKind::Parse,
                            "line " + std::to_string(lineNo) +
                                ": expected 3 values");
            }
            // 一行三个数：输出 R、输出 G、输出 B。顺序与 .cube 规范一致，红变化最快。
            for (int c = 0; c < 3; ++c) {
                float v = 0.0f;
                if (!parseFinite(tok[c], v, true)) {
                    return fail(error, CubeErrorKind::Parse,
                                "line " + std::to_string(lineNo) +
                                    ": invalid or out-of-range sample");
                }
                out.samples.push_back(v);
            }
            ++dataLines;
            continue;
        }

        if (key == "TITLE") {
            if (sawTitle) {
                return fail(error, CubeErrorKind::Parse, "duplicate TITLE");
            }
            sawTitle = true;
            // "TITLE" 长度为 5，后面是可选的引号标题。控制字符丢掉，避免把换行写进标题。
            std::string rest = trim(line.substr(5));
            if (rest.size() >= 2 && rest.front() == '"' && rest.back() == '"') {
                rest = rest.substr(1, rest.size() - 2);
            }
            if (rest.size() > 256) {
                return fail(error, CubeErrorKind::Unsupported,
                            "TITLE exceeds 256 characters");
            }
            for (unsigned char c : rest) {
                if (c < 0x20 && c != '\t') continue;
                out.title.push_back(static_cast<char>(c));
            }
            continue;
        }

        if (key == "LUT_3D_SIZE") {
            if (sawSize) {
                return fail(error, CubeErrorKind::Parse, "duplicate LUT_3D_SIZE");
            }
            if (tok.size() != 2) {
                return fail(error, CubeErrorKind::Parse, "invalid LUT_3D_SIZE");
            }
            float sizeValue = 0.0f;
            if (!parseFinite(tok[1], sizeValue, false)) {
                return fail(error, CubeErrorKind::Parse, "invalid LUT_3D_SIZE");
            }
            // 边长必须是 [2, 65] 的整数。2 是最小的可插值格子，65 是常见主机 LUT 上限。
            int n = static_cast<int>(sizeValue);
            if (static_cast<float>(n) != sizeValue || n < 2 || n > 65) {
                return fail(error, CubeErrorKind::Unsupported,
                            "LUT_3D_SIZE must be an integer in [2, 65]");
            }
            out.size = n;
            sawSize = true;
            expectedSamples = static_cast<std::size_t>(n) * n * n * 3u;
            continue;
        }

        if (key == "DOMAIN_MIN" || key == "DOMAIN_MAX") {
            bool isMin = (key == "DOMAIN_MIN");
            bool& seen = isMin ? sawMin : sawMax;
            if (seen) {
                return fail(error, CubeErrorKind::Parse, "duplicate " + key);
            }
            // 关键字 + R/G/B 三个端点，共 4 个词。缺省时 CubeLut 构造为 [0,1]。
            if (tok.size() != 4) {
                return fail(error, CubeErrorKind::Parse, "invalid " + key);
            }
            for (int c = 0; c < 3; ++c) {
                float v = 0.0f;
                if (!parseFinite(tok[c + 1], v, false)) {
                    return fail(error, CubeErrorKind::Parse, "invalid " + key);
                }
                if (isMin) {
                    out.domain_min[c] = v;
                } else {
                    out.domain_max[c] = v;
                }
            }
            seen = true;
            continue;
        }

        // LUT_1D_SIZE、INPUT_RANGE 等走到这里：认识，但本引擎不实现，直接拒绝。
        return fail(error, CubeErrorKind::Unsupported,
                    "unsupported .cube feature: " + key);
    }

    if (!sawSize) {
        return fail(error, CubeErrorKind::Parse, "missing LUT_3D_SIZE");
    }
    // 每个通道的 Domain 必须是正区间，着色器里要做 (c - min) / (max - min)。
    for (int c = 0; c < 3; ++c) {
        if (!(out.domain_max[c] > out.domain_min[c])) {
            return fail(error, CubeErrorKind::Parse,
                        "DOMAIN_MAX must be greater than DOMAIN_MIN");
        }
    }
    // 行数必须正好是 N³。少一行或行内多一个数都会在上面提前失败；这里再核对总数。
    if (dataLines * 3 != expectedSamples ||
        out.samples.size() != expectedSamples) {
        return fail(error, CubeErrorKind::Parse,
                    "LUT data line count does not match LUT_3D_SIZE");
    }
    return true;
}

// 【模块功能】把 CubeLut 原子写成 .cube（先写 .tmp，再改名覆盖目标）。
// 【关键参数】samples 长度必须是 size³ × 3。每个 float 单独占一行，用 %.9g 保证十进制可逆。
bool writeCubeFile(const std::string& path, const CubeLut& lut,
                   std::string& error) {
    if (lut.size < 2 || lut.size > 65) {
        error = "invalid LUT size";
        return false;
    }
    const std::size_t expected =
        static_cast<std::size_t>(lut.size) * lut.size * lut.size * 3u;
    if (lut.samples.size() != expected) {
        error = "sample count mismatch";
        return false;
    }

    std::filesystem::path target(path);
    std::filesystem::path tmp = target;
    tmp += ".tmp";
    {
        std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
        if (!f) {
            error = "cannot open temp file";
            return false;
        }
        f << "TITLE \"ai_color_app\"\n";
        f << "LUT_3D_SIZE " << lut.size << "\n";
        f << "DOMAIN_MIN " << lut.domain_min[0] << ' ' << lut.domain_min[1]
          << ' ' << lut.domain_min[2] << "\n";
        f << "DOMAIN_MAX " << lut.domain_max[0] << ' ' << lut.domain_max[1]
          << ' ' << lut.domain_max[2] << "\n";
        char buf[64];
        // 每个 float 独占一行，%.9g 保留足够位数，便于再解析回同一个值。
        // 正式交给用户的 .cube 由 Python 导出，那里按规范每行写 R G B 三个数。
        for (float v : lut.samples) {
            if (!std::isfinite(v)) {
                error = "non-finite sample";
                return false;
            }
            std::snprintf(buf, sizeof(buf), "%.9g", static_cast<double>(v));
            f << buf << "\n";
        }
        f.flush();
        if (!f.good()) {
            error = "write failed";
            return false;
        }
    }
    std::error_code ec;
    std::filesystem::remove(target, ec);
    std::filesystem::rename(tmp, target, ec);
    if (ec) {
        error = "rename failed: " + ec.message();
        return false;
    }
    return true;
}
