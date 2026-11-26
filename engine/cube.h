#pragma once

#include <string>
#include <vector>

// P0 subset of the Iridas .cube format. This is deliberately strict: an
// unsupported or ambiguous file must fail instead of being misread.
struct CubeLut {
    int size = 0;
    float domain_min[3] = {0.0f, 0.0f, 0.0f};
    float domain_max[3] = {1.0f, 1.0f, 1.0f};
    std::string title;
    // R fastest, B slowest: index = 3 * (r + N * (g + N * b)).
    std::vector<float> samples;
};

enum class CubeErrorKind { Parse, Unsupported, Io };

struct CubeError {
    CubeErrorKind kind = CubeErrorKind::Parse;
    std::string message;
};

// Returns true on success. `error` is filled otherwise.
bool loadCubeFile(const std::string& path, CubeLut& out, CubeError& error);

// Writes a .cube atomically (tmp file + rename). Used only by tests/self-check;
// the production exporter lives in Python.
bool writeCubeFile(const std::string& path, const CubeLut& lut,
                   std::string& error);
