#pragma once

#include <cstdint>
#include <string>
#include <vector>

// Internal straight (non-premultiplied) RGBA8 bridge between Python and the
// render worker. File layout:
//   8 bytes  magic "ACRGBA01"
//   4 x little-endian uint32: width, height, row_stride, format
//   width * height * 4 bytes, row 0 = top of the image
// format 1 = straight RGBA8. row_stride must equal width * 4.
struct RgbaImage {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::vector<std::uint8_t> pixels;
};

enum class RgbaErrorKind { Invalid, Io };

struct RgbaError {
    RgbaErrorKind kind = RgbaErrorKind::Invalid;
    std::string message;
};

bool loadRgbaFile(const std::string& path, RgbaImage& out, RgbaError& error);

// Writes to `path + ".tmp"`, flushes and closes, then renames over `path`.
bool writeRgbaFileAtomic(const std::string& path, const RgbaImage& image,
                         std::string& error);
