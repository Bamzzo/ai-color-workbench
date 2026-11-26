// ============================================================================
// 【文件总体作用】
//   Python 与离屏渲染进程之间的像素桥。两边不传 PNG，而传一份布局固定的
//   二进制文件：24 字节头 + 紧凑直通 RGBA8。渲染工人读入后直接 glTexImage2D，
//   画完再用同一格式原子写回。
//
// 【输入与输出】
//   输入：路径，或内存中的 RgbaImage（width、height、pixels）。
//   输出：解析后的 RgbaImage，或覆盖写入的 ACRGBA01 文件。
//
// 【核心协议】
//   魔数 8 字节 "ACRGBA01"
//   随后 4 个小端 uint32：宽、高、行跨度、格式
//   格式值 1 = 直通（非预乘）RGBA8，行跨度必须等于 width * 4
//   像素区从第 24 字节开始，第 0 行是图像顶部，长度 = 宽 × 高 × 4
// ============================================================================
#include "rgba_bridge.h"

#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>

namespace {

// 8 字节魔数。版本号放在末尾的 "01"，格式不兼容时可以改号而不是猜布局。
constexpr char kMagic[8] = {'A', 'C', 'R', 'G', 'B', 'A', '0', '1'};
constexpr std::uint32_t kHeaderBytes = 24;
constexpr std::uint32_t kFormatStraightRgba8 = 1;  // 直通 RGBA8，Alpha 不预乘到 RGB 上。
constexpr std::uint32_t kMaxSide = 16384;          // 单边上限，挡住异常头里的巨大宽高。
constexpr std::uint64_t kMaxPixels = 40ull * 1000ull * 1000ull;  // 最多约 4000 万像素。

// 从小端 4 字节还原 uint32。文件协议固定小端，不依赖本机字节序。
std::uint32_t readLe32(const unsigned char* p) {
    return static_cast<std::uint32_t>(p[0]) |
           (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16) |
           (static_cast<std::uint32_t>(p[3]) << 24);
}

// 把 uint32 拆成小端 4 字节写入头。低地址放低 8 位。
void writeLe32(unsigned char* p, std::uint32_t v) {
    p[0] = static_cast<unsigned char>(v & 0xFF);
    p[1] = static_cast<unsigned char>((v >> 8) & 0xFF);
    p[2] = static_cast<unsigned char>((v >> 16) & 0xFF);
    p[3] = static_cast<unsigned char>((v >> 24) & 0xFF);
}

bool fail(RgbaError& error, RgbaErrorKind kind, const std::string& message) {
    error.kind = kind;
    error.message = message;
    return false;
}

}  // namespace

// 【模块功能】读取 ACRGBA01 文件并校验头与文件长度严格一致。
// 【关键参数】头布局：偏移 0 魔数，8 宽，12 高，16 行跨度，20 格式。
// 【失败策略】尺寸、格式、长度任一不符都拒绝，避免把错位的字节当成像素送进 GPU。
bool loadRgbaFile(const std::string& path, RgbaImage& out, RgbaError& error) {
    out = RgbaImage{};
    error = RgbaError{};

    std::error_code ec;
    std::uintmax_t fileSize = std::filesystem::file_size(path, ec);
    if (ec) return fail(error, RgbaErrorKind::Io, "cannot stat RGBA file");

    std::ifstream f(std::filesystem::path(path), std::ios::binary);
    if (!f) return fail(error, RgbaErrorKind::Io, "cannot open RGBA file");

    unsigned char header[kHeaderBytes];
    f.read(reinterpret_cast<char*>(header), kHeaderBytes);
    if (f.gcount() != static_cast<std::streamsize>(kHeaderBytes)) {
        return fail(error, RgbaErrorKind::Invalid, "RGBA header truncated");
    }
    // 魔数不符说明这不是本协议文件（例如误把 PNG 或半截临时文件交给工人进程）。
    if (std::memcmp(header, kMagic, 8) != 0) {
        return fail(error, RgbaErrorKind::Invalid, "bad RGBA magic");
    }
    std::uint32_t width = readLe32(header + 8);
    std::uint32_t height = readLe32(header + 12);
    std::uint32_t stride = readLe32(header + 16);
    std::uint32_t format = readLe32(header + 20);

    if (format != kFormatStraightRgba8) {
        return fail(error, RgbaErrorKind::Invalid, "unsupported RGBA format");
    }
    if (width == 0 || height == 0 || width > kMaxSide || height > kMaxSide) {
        return fail(error, RgbaErrorKind::Invalid, "invalid RGBA dimensions");
    }
    const std::uint64_t pixels = static_cast<std::uint64_t>(width) * height;
    if (pixels > kMaxPixels) {
        return fail(error, RgbaErrorKind::Invalid, "RGBA image exceeds 40 MP");
    }
    // 不接受行填充。stride 必须是 width*4，这样缓冲可以直接交给 glTexImage2D。
    const std::uint64_t expectedStride = static_cast<std::uint64_t>(width) * 4ull;
    if (stride != expectedStride) {
        return fail(error, RgbaErrorKind::Invalid, "row_stride must be width*4");
    }
    const std::uint64_t expectedBytes = pixels * 4ull;
    const std::uint64_t expectedTotal = kHeaderBytes + expectedBytes;
    // 文件长度必须正好等于头 + 像素。多出来或少一字节都判无效，防止尾部垃圾被忽略。
    if (fileSize != expectedTotal) {
        return fail(error, RgbaErrorKind::Invalid,
                    "RGBA file length does not match header");
    }

    out.width = width;
    out.height = height;
    out.pixels.resize(static_cast<std::size_t>(expectedBytes));
    f.read(reinterpret_cast<char*>(out.pixels.data()),
           static_cast<std::streamsize>(out.pixels.size()));
    if (f.gcount() != static_cast<std::streamsize>(out.pixels.size())) {
        return fail(error, RgbaErrorKind::Io, "short read of RGBA pixels");
    }
    return true;
}

// 【模块功能】原子写出 RGBA 文件：先写 path.tmp，关闭后再改名替换 path。
// 【关键参数】像素字节数必须等于 width * height * 4，格式字段固定写 1。
// 先写临时文件是为了读者不会看到“头已更新、像素还没写完”的半截文件。
bool writeRgbaFileAtomic(const std::string& path, const RgbaImage& image,
                         std::string& error) {
    if (image.width == 0 || image.height == 0) {
        error = "empty image";
        return false;
    }
    const std::uint64_t pixels =
        static_cast<std::uint64_t>(image.width) * image.height;
    const std::uint64_t expectedBytes = pixels * 4ull;
    if (image.pixels.size() != expectedBytes) {
        error = "pixel buffer size mismatch";
        return false;
    }

    std::filesystem::path target(path);
    std::filesystem::path tmp = target;
    tmp += ".tmp";

    unsigned char header[kHeaderBytes];
    std::memcpy(header, kMagic, 8);
    writeLe32(header + 8, image.width);
    writeLe32(header + 12, image.height);
    writeLe32(header + 16, image.width * 4u);       // 行跨度 = 宽 × 4 字节
    writeLe32(header + 20, kFormatStraightRgba8);   // 格式 1：直通 RGBA8

    {
        std::ofstream f(tmp, std::ios::binary | std::ios::trunc);
        if (!f) {
            error = "cannot open temp RGBA file";
            return false;
        }
        f.write(reinterpret_cast<const char*>(header), kHeaderBytes);
        f.write(reinterpret_cast<const char*>(image.pixels.data()),
                static_cast<std::streamsize>(image.pixels.size()));
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
