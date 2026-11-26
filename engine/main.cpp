// ============================================================================
// 【文件总体作用】
//   render_worker 的进程入口。Python 主程序把一次调色任务写成 JSON，
//   本进程读请求、校验路径、载入 ACRGBA01 原图和 .cube LUT，调用 GlRenderer
//   完成离屏绘制，再把结果原子写回，并写出一份 JSON 响应。
//
// 【输入与输出】
//   输入：--request <绝对路径.json>、--response <绝对路径.json>、可选 --shaders。
//         请求字段包括 protocol_version、job_id、路径、revision、strength。
//   输出：响应 JSON（status、错误码、回读耗时）以及 output_rgba 指向的像素文件。
//         进程用 ExitProcess 结束，避开本机 Mesa 在 glfwTerminate 里的异常退出。
//
// 【核心技术点】
//   本文件本身不发 gl* 调用，它把“读图 → 解析 LUT → init → render → 写回”
//   收成一次闭环，并在 --selftest 里用恒等 / 交换 / 纯色 LUT 核对 GPU 查表。
// ============================================================================
#define NOMINMAX
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "cube.h"
#include "gl_renderer.h"
#include "json_lite.h"
#include "rgba_bridge.h"

namespace fs = std::filesystem;

namespace {

constexpr const char* kProtocolVersion = "1.0";

// 一次渲染任务从 JSON 里抽出的字段。路径在校验通过后才转成文件系统路径。
struct Request {
    std::string protocol_version;
    std::string job_id;
    std::string document_id;
    long long revision = 0;
    std::string operation;
    fs::path input_rgba;
    fs::path lut_path;
    fs::path output_rgba;
    double strength = 1.0;
};

// 写回响应 JSON 用的结果。ok 为假时 code/message/stage 描述失败发生在哪一步。
struct JobResult {
    std::string code;
    std::string message;
    std::string stage;
    bool ok = true;
    std::string output_path_utf8;
    double render_readback_ms = 0.0;
};

// 【模块功能】结束进程，不走 C 运行库的静态析构。
// 本机 Mesa 24.3.4 曾在 glfwTerminate 里异常终止。响应文件已经原子提交之后，
// 工人进程直接 ExitProcess，把这个已知问题关在隔离进程里，不拖垮主程序。
[[noreturn]] void finish(int code) {
    std::fflush(stdout);
    std::fflush(stderr);
    ::ExitProcess(static_cast<UINT>(code));
}

void trace(const char* stage) {
    if (std::getenv("AI_COLOR_TRACE") != nullptr) {
        std::fprintf(stderr, "[trace] %s\n", stage);
        std::fflush(stderr);
    }
}

std::string toUtf8(const fs::path& p) {
    const std::u16string u16 = p.u16string();
    std::string out;
    out.reserve(u16.size());
    for (char16_t c : u16) {
        if (c < 0x80) {
            out.push_back(static_cast<char>(c));
        } else if (c < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (c >> 6)));
            out.push_back(static_cast<char>(0x80 | (c & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xE0 | (c >> 12)));
            out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (c & 0x3F)));
        }
    }
    return out;
}

fs::path fromUtf8(const std::string& s) { return fs::u8path(s); }

std::string readTextLimited(const fs::path& path, std::size_t limit,
                            std::string& error) {
    std::error_code ec;
    const std::uintmax_t size = fs::file_size(path, ec);
    if (ec) {
        error = "cannot stat request file";
        return {};
    }
    if (size > limit) {
        error = "request file too large";
        return {};
    }
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        error = "cannot open request file";
        return {};
    }
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

bool requireString(const jsonlite::Object& obj, const char* key,
                   std::string& out, std::string& error, std::size_t maxLen) {
    const jsonlite::Value* v = obj.find(key);
    if (v == nullptr || v->type != jsonlite::Value::Type::String) {
        error = std::string("missing or non-string field: ") + key;
        return false;
    }
    if (v->text.empty() || v->text.size() > maxLen) {
        error = std::string("invalid string length: ") + key;
        return false;
    }
    for (unsigned char c : v->text) {
        if (c < 0x20) {
            error = std::string("control character in: ") + key;
            return false;
        }
    }
    out = v->text;
    return true;
}

// 【模块功能】校验请求 JSON。
// 【关键参数】protocol_version 必须是 "1.0"；operation 必须是 "render"；
// strength 若出现则必须落在 [0,1]；三条路径都必须是绝对路径。
// revision 还要求是不超过 2^53 的非负整数，避免超出 JSON 数字的精确整数范围。
bool parseRequest(const jsonlite::Object& obj, Request& out,
                  std::string& error) {
    if (!requireString(obj, "protocol_version", out.protocol_version, error, 32)) {
        return false;
    }
    if (out.protocol_version != kProtocolVersion) {
        error = "UNSUPPORTED_VERSION";
        return false;
    }
    if (!requireString(obj, "job_id", out.job_id, error, 128)) return false;
    if (!requireString(obj, "document_id", out.document_id, error, 128)) {
        return false;
    }
    if (!requireString(obj, "operation", out.operation, error, 32)) return false;
    if (out.operation != "render") {
        error = "unsupported operation";
        return false;
    }

    const jsonlite::Value* rev = obj.find("revision");
    if (rev == nullptr || rev->type != jsonlite::Value::Type::Number ||
        !(rev->number >= 0.0) || rev->number > 9007199254740992.0 ||
        std::floor(rev->number) != rev->number) {
        error = "missing or invalid revision";
        return false;
    }
    out.revision = static_cast<long long>(rev->number);

    std::string pathText;
    if (!requireString(obj, "input_rgba", pathText, error, 4096)) return false;
    out.input_rgba = fromUtf8(pathText);
    if (!requireString(obj, "lut_path", pathText, error, 4096)) return false;
    out.lut_path = fromUtf8(pathText);
    if (!requireString(obj, "output_rgba", pathText, error, 4096)) return false;
    out.output_rgba = fromUtf8(pathText);

    const jsonlite::Value* strength = obj.find("strength");
    if (strength != nullptr) {
        if (strength->type != jsonlite::Value::Type::Number ||
            !(strength->number >= 0.0) || !(strength->number <= 1.0)) {
            error = "strength must be a number in [0,1]";
            return false;
        }
        out.strength = strength->number;
    }

    for (const fs::path* p : {&out.input_rgba, &out.lut_path, &out.output_rgba}) {
        if (!p->is_absolute()) {
            error = "all paths must be absolute";
            return false;
        }
    }
    return true;
}

bool sameDirectory(const fs::path& a, const fs::path& b) {
    std::error_code ec;
    fs::path ca = fs::weakly_canonical(a, ec);
    if (ec) return false;
    fs::path cb = fs::weakly_canonical(b, ec);
    if (ec) return false;
    return ca == cb;
}

std::string jsonResponse(const Request& req, const JobResult& result) {
    std::ostringstream ss;
    ss << "{";
    ss << "\"protocol_version\":\"" << kProtocolVersion << "\",";
    ss << "\"job_id\":\"" << jsonlite::escape(req.job_id) << "\",";
    ss << "\"document_id\":\"" << jsonlite::escape(req.document_id) << "\",";
    ss << "\"revision\":" << req.revision << ",";
    ss << "\"status\":\"" << (result.ok ? "ok" : "error") << "\",";
    if (result.ok) {
        ss << "\"error\":null,";
        ss << "\"output_rgba\":\""
           << jsonlite::escape(result.output_path_utf8) << "\",";
    } else {
        ss << "\"error\":{\"code\":\"" << jsonlite::escape(result.code)
           << "\",\"message\":\"" << jsonlite::escape(result.message)
           << "\",\"stage\":\"" << jsonlite::escape(result.stage) << "\"},";
        ss << "\"output_rgba\":null,";
    }
    ss << "\"metrics\":{\"render_readback_ms\":";
    if (result.render_readback_ms > 0.0) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.3f", result.render_readback_ms);
        ss << buf;
    } else {
        ss << "null";
    }
    ss << "}";
    ss << "}";
    return ss.str();
}

bool writeTextAtomic(const fs::path& target, const std::string& text,
                     std::string& error) {
    fs::path tmp = target;
    tmp += ".tmp";
    {
        std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
        if (!f) {
            error = "cannot open response temp file";
            return false;
        }
        f.write(text.data(), static_cast<std::streamsize>(text.size()));
        f.flush();
        if (!f.good()) {
            error = "cannot write response";
            return false;
        }
    }
    std::error_code ec;
    fs::remove(target, ec);
    fs::rename(tmp, target, ec);
    if (ec) {
        error = "cannot commit response: " + ec.message();
        return false;
    }
    return true;
}

int exitCodeFor(const JobResult& result) {
    if (result.ok) return 0;
    const std::string& c = result.code;
    if (c == "LUT_UNSUPPORTED") return 3;
    if (c == "GPU_INIT_FAILED" || c == "GPU_RENDER_FAILED" ||
        c == "GPU_LIMIT") {
        return 4;
    }
    if (c == "EXPORT_IO") return 5;
    return 2;
}

fs::path executableDirectory() {
    std::vector<wchar_t> buf(32768);
    DWORD n = ::GetModuleFileNameW(nullptr, buf.data(),
                                  static_cast<DWORD>(buf.size()));
    if (n == 0) return fs::current_path();
    return fs::path(std::wstring(buf.data(), n)).parent_path();
}

// 【模块功能】GPU 自检：恒等 LUT 应几乎原样返回，交换/纯红/纯黑 LUT 应按查表结果变色。
// 【渲染管线阶段】init → 上传 256×4 测试图 → render → 与 CPU 期望逐像素比对。
// 允许 RGB 最多差 1（8 位量化），Alpha 必须逐字节相同。
int runSelfTest(const fs::path& shaderDir) {
    // 故意不 delete。本机 Mesa 可能在 glfwTerminate 里中止；自检结果打印后
    // 进程经 ExitProcess 退出，不走析构。

    GlRenderer* rendererPtr = new GlRenderer();
    GlRenderer& renderer = *rendererPtr;
    std::string error;
    if (!renderer.init(toUtf8(shaderDir), error)) {
        std::printf("SELFTEST FAIL init: %s\n", error.c_str());
        return 4;
    }
    std::printf("GL %s\n", renderer.glInfo().c_str());

    // 256×4 的非对称图案，Alpha 随 x 变化。宽而扁，方便看出左右是否被写反。
    RgbaImage image;
    image.width = 256;
    image.height = 4;
    image.pixels.resize(static_cast<std::size_t>(image.width) * image.height * 4u);
    for (std::uint32_t y = 0; y < image.height; ++y) {
        for (std::uint32_t x = 0; x < image.width; ++x) {
            std::size_t i = (static_cast<std::size_t>(y) * image.width + x) * 4u;
            image.pixels[i + 0] = static_cast<std::uint8_t>(x);
            image.pixels[i + 1] = static_cast<std::uint8_t>((x * 7u + y * 53u) & 0xFF);
            image.pixels[i + 2] = static_cast<std::uint8_t>((255u - x + y * 11u) & 0xFF);
            image.pixels[i + 3] = static_cast<std::uint8_t>(255u - (x & 0xFF));
        }
    }
    image.pixels[0] = 255; image.pixels[1] = 0; image.pixels[2] = 0; image.pixels[3] = 255;

    // 在 CPU 上生成一张边长为 n 的 LUT。格子坐标按 R 最快、B 最慢，与 .cube 一致。
    // identity：输出等于输入格子；black / red：整张表变成常数色；swap：对调 R 与 B。
    auto makeLut = [](int n, const std::string& kind) {
        CubeLut lut;
        lut.size = n;
        lut.samples.resize(static_cast<std::size_t>(n) * n * n * 3u);
        for (int b = 0; b < n; ++b) {
            for (int g = 0; g < n; ++g) {
                for (int r = 0; r < n; ++r) {
                    float v[3] = {static_cast<float>(r) / (n - 1),
                                  static_cast<float>(g) / (n - 1),
                                  static_cast<float>(b) / (n - 1)};
                    if (kind == "black") {
                        v[0] = v[1] = v[2] = 0.0f;
                    } else if (kind == "red") {
                        v[0] = 1.0f; v[1] = v[2] = 0.0f;
                    } else if (kind == "swap") {
                        std::swap(v[0], v[2]);
                    }
                    std::size_t i =
                        (static_cast<std::size_t>(b) * n * n + g * n + r) * 3u;
                    lut.samples[i] = v[0];
                    lut.samples[i + 1] = v[1];
                    lut.samples[i + 2] = v[2];
                }
            }
        }
        return lut;
    };

    bool allOk = true;
    for (int n : {17, 33, 65}) {
        CubeLut lut = makeLut(n, "identity");
        RgbaImage out;
        if (!renderer.render(image, lut, 1.0f, out, error)) {
            std::printf("SELFTEST FAIL identity-%d: %s\n", n, error.c_str());
            allOk = false;
            continue;
        }
        int maxDev = 0, alphaDev = 0;
        for (std::size_t i = 0; i < out.pixels.size(); i += 4) {
            for (int c = 0; c < 3; ++c) {
                maxDev = std::max(maxDev, std::abs(int(out.pixels[i + c]) -
                                                   int(image.pixels[i + c])));
            }
            alphaDev = std::max(alphaDev, std::abs(int(out.pixels[i + 3]) -
                                                   int(image.pixels[i + 3])));
        }
        std::printf("SELFTEST identity n=%d max_dev=%d alpha_dev=%d\n", n,
                    maxDev, alphaDev);
        if (maxDev > 1 || alphaDev != 0) allOk = false;
    }

    for (const char* kind : {"swap", "red", "black"}) {
        CubeLut lut = makeLut(33, kind);
        RgbaImage out;
        if (!renderer.render(image, lut, 1.0f, out, error)) {
            std::printf("SELFTEST FAIL %s: %s\n", kind, error.c_str());
            allOk = false;
            continue;
        }
        int maxDev = 0;
        for (std::size_t i = 0; i < out.pixels.size(); i += 4) {
            int expected[3] = {image.pixels[i], image.pixels[i + 1],
                               image.pixels[i + 2]};
            if (std::string(kind) == "swap") std::swap(expected[0], expected[2]);
            if (std::string(kind) == "red") { expected[0] = 255; expected[1] = 0; expected[2] = 0; }
            if (std::string(kind) == "black") { expected[0] = expected[1] = expected[2] = 0; }
            for (int c = 0; c < 3; ++c) {
                maxDev = std::max(maxDev, std::abs(int(out.pixels[i + c]) -
                                                   expected[c]));
            }
        }
        std::printf("SELFTEST %s max_dev=%d\n", kind, maxDev);
        if (maxDev > 1) allOk = false;
    }

    std::printf("SELFTEST %s\n", allOk ? "PASS" : "FAIL");
    return allOk ? 0 : 4;
}

}  // namespace

// 【模块功能】宽字符入口。Windows 下用 wmain 接收 Unicode 路径，避免中文路径被窄字符截断。
// 【渲染管线阶段】解析参数 → 校验请求 → loadRgbaFile → loadCubeFile →
// GlRenderer::init → render → writeRgbaFileAtomic → 原子写响应 JSON → ExitProcess。
int wmain(int argc, wchar_t** argv) {
    fs::path requestPath;
    fs::path responsePath;
    fs::path shaderDir;
    bool selftest = false;

    for (int i = 1; i < argc; ++i) {
        std::wstring arg = argv[i];
        if (arg == L"--request" && i + 1 < argc) {
            requestPath = fs::path(argv[++i]);
        } else if (arg == L"--response" && i + 1 < argc) {
            responsePath = fs::path(argv[++i]);
        } else if (arg == L"--shaders" && i + 1 < argc) {
            shaderDir = fs::path(argv[++i]);
        } else if (arg == L"--selftest") {
            selftest = true;
        } else {
            std::fprintf(stderr, "unknown argument\n");
            return 2;
        }
    }

    if (shaderDir.empty()) shaderDir = executableDirectory() / "shaders";

    if (selftest) {
        int code = runSelfTest(shaderDir);
        finish(code);
    }

    if (requestPath.empty() || responsePath.empty()) {
        std::fprintf(stderr, "usage: render_worker --request <json> --response <json>\n");
        return 2;
    }
    if (!requestPath.is_absolute() || !responsePath.is_absolute()) {
        std::fprintf(stderr, "request and response paths must be absolute\n");
        return 2;
    }

    Request request;
    JobResult result;
    std::string parseError;
    {
        std::string text = readTextLimited(requestPath, 65536, parseError);
        if (text.empty()) {
            result.ok = false;
            result.code = "INVALID_REQUEST";
            result.message = parseError.empty() ? "empty request" : parseError;
            result.stage = "request";
        } else {
            jsonlite::Object obj;
            std::string jsonError;
            if (!jsonlite::parseObject(text, obj, jsonError)) {
                result.ok = false;
                result.code = "INVALID_REQUEST";
                result.message = "invalid JSON: " + jsonError;
                result.stage = "request";
            } else if (!parseRequest(obj, request, parseError)) {
                result.ok = false;
                result.code = (parseError == "UNSUPPORTED_VERSION")
                                  ? "UNSUPPORTED_VERSION"
                                  : "INVALID_REQUEST";
                result.message = parseError;
                result.stage = "request";
            }
        }
    }

    if (result.ok) {
        // 输出与响应必须落在请求文件所在的任务目录里。
        // 工人进程可以读缓存中的输入，但不能把结果写到目录之外。
        const fs::path jobDir = requestPath.parent_path();
        bool contained = !jobDir.empty() && request.output_rgba.is_absolute();
        contained = contained &&
                    sameDirectory(request.output_rgba.parent_path(), jobDir);
        contained = contained &&
                    sameDirectory(responsePath.parent_path(), jobDir);
        if (!contained) {
            result.ok = false;
            result.code = "INVALID_REQUEST";
            result.message = "all files must be inside the job directory";
            result.stage = "request";
        }
    }

    trace("request parsed");
    if (result.ok) {
        RgbaImage input;
        RgbaError imageError;
        if (!loadRgbaFile(toUtf8(request.input_rgba), input, imageError)) {
            result.ok = false;
            result.code = imageError.kind == RgbaErrorKind::Io ? "EXPORT_IO"
                                                               : "IMAGE_INVALID";
            result.message = imageError.message;
            result.stage = "image";
        } else {
            trace("image loaded");
            CubeLut lut;
            CubeError lutError;
            if (!loadCubeFile(toUtf8(request.lut_path), lut, lutError)) {
                result.ok = false;
                if (lutError.kind == CubeErrorKind::Unsupported) {
                    result.code = "LUT_UNSUPPORTED";
                } else if (lutError.kind == CubeErrorKind::Io) {
                    result.code = "EXPORT_IO";
                } else {
                    result.code = "LUT_PARSE_ERROR";
                }
                result.message = lutError.message;
                result.stage = "lut";
            } else {
                trace("lut loaded");
                // 不用栈上对象持有渲染器。本机 Mesa 可能在 glfwTerminate 里中止；
                // 本进程是一次性的，响应提交后经 ExitProcess 退出。
                GlRenderer* rendererPtr = new GlRenderer();
                GlRenderer& renderer = *rendererPtr;
                std::string glError;
                if (!renderer.init(toUtf8(shaderDir), glError)) {
                    std::printf("GL %s\n", renderer.glInfo().c_str());
                    result.ok = false;
                    result.code = "GPU_INIT_FAILED";
                    result.message = glError;
                    result.stage = "gpu";
                } else {
                    trace("gl initialized");
                    std::printf("GL %s\n", renderer.glInfo().c_str());
                    // 计时只包住 render：上传、绘制、glReadPixels 回读，不含写文件。
                    const auto started = std::chrono::steady_clock::now();
                    RgbaImage output;
                    std::string renderError;
                    // 闭环的 GPU 一步：原图与 LUT 已在 CPU 内存，由此进入离屏管线。
                    const bool rendered = renderer.render(
                        input, lut, static_cast<float>(request.strength), output,
                        renderError);
                    const auto stopped = std::chrono::steady_clock::now();
                    result.render_readback_ms =
                        std::chrono::duration<double, std::milli>(stopped - started)
                            .count();
                    if (!rendered) {
                        result.ok = false;
                        result.code = "GPU_RENDER_FAILED";
                        result.message = renderError;
                        result.stage = "gpu";
                    } else {
                        std::string writeError;
                        if (!writeRgbaFileAtomic(toUtf8(request.output_rgba),
                                                 output, writeError)) {
                            result.ok = false;
                            result.code = "EXPORT_IO";
                            result.message = writeError;
                            result.stage = "io";
                        } else {
                            trace("output written");
                            result.output_path_utf8 = toUtf8(request.output_rgba);
                        }
                    }
                }
            }
        }
    }

    if (!result.ok) {
        std::fprintf(stderr, "render_worker: %s (%s) at %s\n",
                     result.code.c_str(), result.message.c_str(),
                     result.stage.c_str());
    }

    trace("building response");
    const std::string responseText = jsonResponse(request, result);
    std::string responseError;
    if (!writeTextAtomic(responsePath, responseText, responseError)) {
        std::fprintf(stderr, "render_worker: cannot write response: %s\n",
                     responseError.c_str());
        finish(5);
    }

    trace("response written");
    finish(exitCodeFor(result));
}
