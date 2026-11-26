// ============================================================================
// 【文件总体作用】
//   GlRenderer 的实现：在一块看不见的 OpenGL 3.3 画布上完成
//   “上传原图 → 上传 3D LUT → 绑定 FBO → 画全屏三角形 → 读回像素”。
//   这是整套系统里唯一真正碰 GPU 的 C++ 模块，Python 只负责把参数烘焙成 LUT。
//
// 【输入与输出】
//   输入：RGBA8 字节缓冲、.cube 解析后的 float 采样、强度、两份 GLSL 源码。
//   输出：同样宽高的 RGBA8 缓冲。失败时 error 带有出错阶段（上传、FBO、绘制、回读）。
//
// 【核心技术点】
//   GLFW 隐藏窗口与 GLAD 加载、着色器编译链接、GL_NEAREST 的 2D 原图、
//   GL_LINEAR 的 GL_RGB32F 三维纹理（8 邻域三线性插值）、
//   关闭 GL_FRAMEBUFFER_SRGB 避免硬件再做一次 Gamma、
//   自定义 FBO、glDrawArrays 绘制 3 个顶点、glReadPixels 同步回读。
// ============================================================================
#define NOMINMAX
#define GLFW_INCLUDE_NONE
#include "gl_renderer.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>

namespace {

// 按二进制方式读入着色器文本。空文件或打不开都返回空串，由调用方报“读不到着色器”。
std::string readTextFile(const std::filesystem::path& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return std::string();
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

// 把 glGetError 的枚举翻译成可读名字，便于日志里直接看到是“非法操作”还是“显存不足”。
std::string glErrorName(GLenum e) {
    switch (e) {
        case GL_NO_ERROR: return "GL_NO_ERROR";
        case GL_INVALID_ENUM: return "GL_INVALID_ENUM";
        case GL_INVALID_VALUE: return "GL_INVALID_VALUE";
        case GL_INVALID_OPERATION: return "GL_INVALID_OPERATION";
        case GL_INVALID_FRAMEBUFFER_OPERATION:
            return "GL_INVALID_FRAMEBUFFER_OPERATION";
        case GL_OUT_OF_MEMORY: return "GL_OUT_OF_MEMORY";
        default: return "GL_ERROR_" + std::to_string(e);
    }
}

// 取出并清空当前错误标志。OpenGL 的错误是“粘滞”的，不取走就会污染后续判断。
bool checkGl(const char* where, std::string& error) {
    GLenum e = glGetError();
    if (e == GL_NO_ERROR) return true;
    error = std::string("OpenGL error at ") + where + ": " + glErrorName(e);
    return false;
}

// 【模块功能】编译单个着色器对象（顶点或片元）。
// 【关键参数】type 为 GL_VERTEX_SHADER 或 GL_FRAGMENT_SHADER；source 是完整 GLSL 文本。
// 【渲染管线阶段】程序链接之前。编译失败会删掉半成品并返回 0。
GLuint compileShader(GLenum type, const std::string& source,
                     const std::string& label, std::string& error) {
    // glCreateShader：向驱动申请一个着色器对象，返回的是名字（无符号整数），不是指针。
    GLuint shader = glCreateShader(type);
    if (shader == 0) {
        error = "glCreateShader failed for " + label;
        return 0;
    }
    const char* src = source.c_str();
    // glShaderSource：把 GLSL 源码交给这个对象。count=1 表示只有一段字符串；
    // length 传 nullptr 表示每段都以 '\0' 结尾，驱动自己量长度。
    glShaderSource(shader, 1, &src, nullptr);
    // glCompileShader：同步编译。失败与否要另外用 GL_COMPILE_STATUS 查询，不会抛异常。
    glCompileShader(shader);
    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (ok != GL_TRUE) {
        char log[4096] = {0};
        // 取出编译器的报错原文（行号、语法问题），截断到 4095 字节以免溢出。
        glGetShaderInfoLog(shader, sizeof(log) - 1, nullptr, log);
        error = "shader compile failed (" + label + "): " + log;
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

// 一次 render 调用里临时申请的 GPU 对象。函数结束前全部删除，不留到下一帧。
struct GlObjects {
    GLuint inputTexture = 0;  // 原图，GL_TEXTURE_2D / GL_RGBA8
    GLuint lutTexture = 0;    // 查找表，GL_TEXTURE_3D / GL_RGB32F
    GLuint colorTexture = 0;  // 离屏颜色附件，画完后从这里读回
    GLuint fbo = 0;           // 帧缓冲对象，把绘制目标从窗口改到 colorTexture
};

}  // namespace

GlRenderer::~GlRenderer() { shutdown(); }

// 【模块功能】一次性准备上下文、着色器程序和空 VAO，并设好“像素精确”的全局状态。
// 【渲染管线阶段】任何 render 之前。重复调用直接返回成功，避免重建窗口。
bool GlRenderer::init(const std::string& shaderDir, std::string& error) {
    if (initialized_) return true;
    if (!initGlfw(error)) {
        shutdown();
        return false;
    }
    if (!loadProgram(shaderDir, error)) {
        shutdown();
        return false;
    }
    // glGenVertexArrays：申请 1 个顶点数组对象。
    // Core Profile 规定，glDrawArrays 前必须有 VAO 处于绑定状态，哪怕顶点数据完全由着色器生成。
    glGenVertexArrays(1, &vao_);
    glBindVertexArray(vao_);
    if (!checkGl("glGenVertexArrays", error)) {
        shutdown();
        return false;
    }

    // 下面这一组开关把管线收成“1 个像素进、1 个像素出”的查表器，不让固定功能偷偷改颜色。
    glDisable(GL_DEPTH_TEST);   // 全屏三角形没有前后遮挡，深度测试只会多一次无意义的比较。
    glDisable(GL_BLEND);        // 关闭混合：片元颜色直接覆盖附件，不与原内容做 src+dst 叠加。
    glDisable(GL_DITHER);       // 关闭抖动：8 位量化时不要加噪声，保证回读结果可复现。
    glDisable(GL_SCISSOR_TEST); // 关闭剪裁矩形：允许写满整个视口，不被残留的 scissor 框切掉。
    glDisable(GL_CULL_FACE);    // 关闭背面剔除：大三角形的绕序无需关心，三个顶点都必须保留。
    // 关闭帧缓冲 sRGB 编码。若开启，驱动会在写入 GL_RGBA8 时再做一次线性→sRGB。
    // 本管线约定“编码域进、编码域出”（ADR-004），着色器里的数值已经是 sRGB，
    // 再转一次会把中间调压暗，和 CPU 参考对不上。
    glDisable(GL_FRAMEBUFFER_SRGB);
    // 像素传输对齐设为 1 字节。默认是 4，宽度不是 4 的倍数时，行尾会被驱动插入填充字节，
    // 导致上传和 glReadPixels 的布局与紧凑的 RGBA 缓冲错位。
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);  // CPU → GPU 时每行按 1 字节对齐。
    glPixelStorei(GL_PACK_ALIGNMENT, 1);    // GPU → CPU 时每行按 1 字节对齐。
    if (!checkGl("initial state", error)) {
        shutdown();
        return false;
    }

    initialized_ = true;
    return true;
}

// 【模块功能】拉起 GLFW，创建不可见窗口，用 GLAD 填好 OpenGL 函数指针，并核对 3.3 与纹理上限。
// 【渲染管线阶段】上下文创建。此后所有 gl* 调用才合法。
bool GlRenderer::initGlfw(std::string& error) {
    glfwSetErrorCallback([](int code, const char* description) {
        // 失败原因由调用方写入 error 字符串；这里不往 stdout 打字，避免污染工人进程的协议输出。
        (void)code;
        (void)description;
    });

    // glfwInit：初始化窗口库的内部状态。失败通常是显示驱动或运行库缺失。
    if (!glfwInit()) {
        error = "GLFW init failed";
        return false;
    }
    glfwReady_ = true;

    // 不额外指定 GLFW_OPENGL_CORE_PROFILE。本机已知可用的 Mesa/D3D12 路径无论是否加这条
    // hint 都会给出 4.1 core；加上之后，可见窗口路径反而不稳定。版本号仍要求至少 3.3。
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);  // 主版本号下限：3
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);  // 次版本号下限：3，合起来是 OpenGL 3.3
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);       // 窗口不显示。这是离屏工人进程，不需要把画面摆到桌面上。
    glfwWindowHint(GLFW_DOUBLEBUFFER, GLFW_FALSE);  // 单缓冲即可：结果读自 FBO，不靠前后缓冲交换。

    // 64×64 只是上下文的“挂靠表面”。真正的绘制尺寸在 render 里用 glViewport 设成原图大小。
    GLFWwindow* window = glfwCreateWindow(64, 64, "render_worker", nullptr, nullptr);
    if (window == nullptr) {
        error = "GLFW window creation failed";
        return false;
    }
    window_ = window;
    // 把这个窗口的 OpenGL 上下文绑到当前线程。一个线程同时只能有一个 current context。
    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);  // 不等待垂直同步。离屏回读不需要和显示器刷新率对齐。

    // gladLoadGLLoader：用 glfwGetProcAddress 逐个查询 glGenTextures、glDrawArrays 等函数地址。
    // 不加载的话，gl* 函数指针是空的，一调用就崩溃。GLAD 只填指针，不创建上下文。
    if (!gladLoadGLLoader(reinterpret_cast<GLADloadproc>(glfwGetProcAddress))) {
        error = "GLAD loader failed";
        return false;
    }

    // glGetString 返回驱动描述字符串，指针由驱动持有，不要 free。
    const char* version = reinterpret_cast<const char*>(glGetString(GL_VERSION));
    const char* renderer = reinterpret_cast<const char*>(glGetString(GL_RENDERER));
    const char* vendor = reinterpret_cast<const char*>(glGetString(GL_VENDOR));
    glInfo_ = std::string(version ? version : "?") + " | " +
              (renderer ? renderer : "?") + " | " + (vendor ? vendor : "?");

    GLint major = 0, minor = 0;
    // 数值版本比解析 GL_VERSION 字符串可靠，能直接和 3.3 比较。
    glGetIntegerv(GL_MAJOR_VERSION, &major);
    glGetIntegerv(GL_MINOR_VERSION, &minor);
    if (major < 3 || (major == 3 && minor < 3)) {
        error = "OpenGL 3.3 required, got " + std::to_string(major) + "." +
                std::to_string(minor);
        return false;
    }

    // 查询硬件上限，后面拒绝过大的原图和 LUT，避免 glTexImage 在中途才报显存错误。
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maxTextureSize_);
    glGetIntegerv(GL_MAX_3D_TEXTURE_SIZE, &max3dTextureSize_);
    if (maxTextureSize_ < 64 || max3dTextureSize_ < 2) {
        error = "GL texture limits are too small";
        return false;
    }
    if (!checkGl("limits query", error)) return false;
    return true;
}

// 【模块功能】读入两份 GLSL，分别编译，再链接成一个可 glUseProgram 的程序。
// 【渲染管线阶段】顶点着色器 + 片元着色器链接。链完即可删除着色器对象，程序仍保留机器码。
bool GlRenderer::loadProgram(const std::string& shaderDir, std::string& error) {
    std::filesystem::path dir(shaderDir);
    const std::filesystem::path vertPath = dir / "fullscreen.vert";
    const std::filesystem::path fragPath = dir / "grade.frag";
    const std::string vertSrc = readTextFile(vertPath);
    const std::string fragSrc = readTextFile(fragPath);
    if (vertSrc.empty()) {
        error = "cannot read shader: " + vertPath.string();
        return false;
    }
    if (fragSrc.empty()) {
        error = "cannot read shader: " + fragPath.string();
        return false;
    }

    GLuint vert = compileShader(GL_VERTEX_SHADER, vertSrc, vertPath.string(), error);
    if (vert == 0) return false;
    GLuint frag = compileShader(GL_FRAGMENT_SHADER, fragSrc, fragPath.string(), error);
    if (frag == 0) {
        glDeleteShader(vert);
        return false;
    }

    // glCreateProgram：申请程序对象，用来装链接后的整条可编程管线。
    program_ = glCreateProgram();
    // glAttachShader：把已编译的顶点、片元着色器挂到程序上。链接时驱动会把接口（vUv 等）对上。
    glAttachShader(program_, vert);
    glAttachShader(program_, frag);
    // glLinkProgram：生成可执行的 GPU 程序。uniform 位置在链接之后才固定。
    glLinkProgram(program_);
    // 链接完成后着色器对象可以删。程序已经持有链接结果，删的是中间编译单元，不是最终程序。
    glDeleteShader(vert);
    glDeleteShader(frag);

    GLint ok = GL_FALSE;
    glGetProgramiv(program_, GL_LINK_STATUS, &ok);
    if (ok != GL_TRUE) {
        char log[4096] = {0};
        glGetProgramInfoLog(program_, sizeof(log) - 1, nullptr, log);
        error = std::string("shader link failed: ") + log;
        return false;
    }
    return checkGl("link program", error);
}

// 【模块功能】一次完整的离屏调色：上传资源、画、读回、释放本次纹理与 FBO。
// 【关键参数】strength ∈ [0,1]；lut.size ∈ [2,65]；原图单边不得超过 GL_MAX_TEXTURE_SIZE。
// 【渲染管线阶段】纹理上传 → FBO 绑定 → 绘制 → 回读。程序和 VAO 在多次调用之间复用。
bool GlRenderer::render(const RgbaImage& input, const CubeLut& lut,
                        float strength, RgbaImage& output, std::string& error) {
    if (!initialized_) {
        error = "renderer not initialized";
        return false;
    }
    if (input.width == 0 || input.height == 0 || input.pixels.empty()) {
        error = "empty input image";
        return false;
    }
    if (lut.size < 2 || lut.size > 65) {
        error = "invalid LUT size";
        return false;
    }
    if (static_cast<int>(input.width) > maxTextureSize_ ||
        static_cast<int>(input.height) > maxTextureSize_) {
        error = "image exceeds GL_MAX_TEXTURE_SIZE";
        return false;
    }
    if (lut.size > max3dTextureSize_) {
        error = "LUT exceeds GL_MAX_3D_TEXTURE_SIZE";
        return false;
    }
    if (!(strength >= 0.0f && strength <= 1.0f)) {
        error = "strength must be in [0,1]";
        return false;
    }

    const std::size_t expectedLut =
        static_cast<std::size_t>(lut.size) * lut.size * lut.size * 3u;
    if (lut.samples.size() != expectedLut) {
        error = "LUT sample count mismatch";
        return false;
    }

    GlObjects obj;
    bool ok = true;

    // 再次钉死对齐，防止其它代码把 PACK/UNPACK 改回 4。
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);

    // ---------- 上传 2D 原图 ----------
    // glGenTextures：申请 1 个纹理名字。名字本身不含数据，数据要靠后面的 glTexImage2D 填入。
    glGenTextures(1, &obj.inputTexture);
    // glBindTexture(GL_TEXTURE_2D, ...)：后续对 2D 纹理目标的参数和上传都作用在这张纹理上。
    glBindTexture(GL_TEXTURE_2D, obj.inputTexture);
    // MIN/MAG 都用 GL_NEAREST：缩小时和放大时都取最近纹素，不做双线性模糊。
    // 原图与 FBO 等大，一个片元对应一个像素，最近邻才能做到“查表不先把图涂糊”。
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    // GL_CLAMP_TO_EDGE：坐标超出 [0,1] 时取边缘像素，不重复、不环绕，避免采样到对边的颜色。
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    // glTexImage2D：分配并上传 2D 纹理。
    //   level=0           只填基础层，不建 mipmap
    //   internalFormat    GL_RGBA8，GPU 内存里每个纹素 4 个 8 位通道
    //   width, height     原图尺寸
    //   border            必须为 0（旧版边界纹素，Core Profile 已废弃）
    //   format/type       源数据是紧凑的 RGBA 无符号字节，与 RgbaImage 布局一致
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, static_cast<GLsizei>(input.width),
                 static_cast<GLsizei>(input.height), 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, input.pixels.data());
    ok = ok && checkGl("upload input texture", error);

    if (ok) {
        // ---------- 上传 3D LUT ----------
        glGenTextures(1, &obj.lutTexture);
        // GL_TEXTURE_3D：第三维对应蓝色轴。采样坐标 (r, g, b) 直接当成纹理坐标 (s, t, r)。
        glBindTexture(GL_TEXTURE_3D, obj.lutTexture);
        // GL_LINEAR 对 3D 纹理的含义是三线性插值：s/t/r 三个轴各取相邻两个纹素，
        // 一共 8 个角点，按小数部分做权重。这就是 LUT 在格子之间“平滑过渡”的硬件实现，
        // 等价于 CPU 侧的三线性插值，不需要在着色器里手写 8 次取样。
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        // 三个轴都钳到边缘。立方体表面上的颜色不会和另一侧的格子混在一起。
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
        // 明确只有第 0 层。浮点 3D 纹理若不锁住 mipmap 范围，某些驱动会认为纹理不完整。
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_BASE_LEVEL, 0);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAX_LEVEL, 0);
        // glTexImage3D：上传 N×N×N 的浮点查找表。
        //   internalFormat GL_RGB32F  每格 3 个 32 位浮点，保留烘焙时的精度
        //   width/height/depth        都是 lut.size，三条轴等长
        //   format GL_RGB、type GL_FLOAT  源缓冲是紧密排列的 float RGB，R 变化最快
        glTexImage3D(GL_TEXTURE_3D, 0, GL_RGB32F, lut.size, lut.size, lut.size,
                     0, GL_RGB, GL_FLOAT, lut.samples.data());
        // glFinish：等到上传真正完成再继续。避免某些驱动把错误推迟到绘制时才报。
        glFinish();
        ok = ok && checkGl("upload 3D LUT", error);
    }

    if (ok) {
        // ---------- 分配离屏颜色缓冲 ----------
        // 这张纹理不上传像素（data=nullptr），只按原图尺寸分配 GPU 内存，作为绘制目标。
        glGenTextures(1, &obj.colorTexture);
        glBindTexture(GL_TEXTURE_2D, obj.colorTexture);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, static_cast<GLsizei>(input.width),
                     static_cast<GLsizei>(input.height), 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, nullptr);
        ok = ok && checkGl("allocate output texture", error);
    }

    if (ok) {
        // ---------- 自定义帧缓冲 ----------
        // 默认帧缓冲是那扇 64×64 的隐藏窗口。这里新建 FBO，把绘制改道到 colorTexture。
        glGenFramebuffers(1, &obj.fbo);
        // 绑定到 GL_FRAMEBUFFER 等于同时绑定绘制目标和读取目标。
        glBindFramebuffer(GL_FRAMEBUFFER, obj.fbo);
        // 把 colorTexture 的第 0 层挂到颜色附件 0。之后片元着色器写出的 fragColor 就进这张纹理。
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, obj.colorTexture, 0);
        // 附件尺寸、格式必须彼此相容。不完整的 FBO 上绘制会被驱动直接丢弃。
        GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
        if (status != GL_FRAMEBUFFER_COMPLETE) {
            error = "framebuffer incomplete: " + std::to_string(status);
            ok = false;
        }
        // 指定绘制和读取都走颜色附件 0。不设的话，部分驱动仍指着窗口的前后缓冲。
        glDrawBuffer(GL_COLOR_ATTACHMENT0);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
    }

    if (ok) {
        // ---------- 绘制全屏三角形 ----------
        // 视口设成原图像素尺寸。片元数量 = width × height，和回读矩形一致。
        glViewport(0, 0, static_cast<GLsizei>(input.width),
                   static_cast<GLsizei>(input.height));
        glUseProgram(program_);
        // 纹理单元 0 放原图。glUniform1i(..., 0) 告诉采样器 uImage：“去 0 号单元取样”。
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, obj.inputTexture);
        glUniform1i(glGetUniformLocation(program_, "uImage"), 0);
        // 纹理单元 1 放 3D LUT。两个采样器必须绑在不同单元上，否则后一次绑定会顶掉前一张。
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_3D, obj.lutTexture);
        glUniform1i(glGetUniformLocation(program_, "uLut"), 1);
        // Domain 与边长、强度都是本次绘制的 uniform。改它们不用重新链接着色器。
        glUniform3f(glGetUniformLocation(program_, "uDomainMin"),
                    lut.domain_min[0], lut.domain_min[1], lut.domain_min[2]);
        glUniform3f(glGetUniformLocation(program_, "uDomainMax"),
                    lut.domain_max[0], lut.domain_max[1], lut.domain_max[2]);
        glUniform1f(glGetUniformLocation(program_, "uLutSize"),
                    static_cast<float>(lut.size));
        glUniform1f(glGetUniformLocation(program_, "uStrength"), strength);
        glBindVertexArray(vao_);
        // 从顶点 0 开始画 3 个顶点，图元类型是三角形。
        // 没有 VBO：顶点位置由着色器里的 gl_VertexID 生成（见 fullscreen.vert）。
        glDrawArrays(GL_TRIANGLES, 0, 3);
        // 画完再同步一次，确保颜色附件写完，后面的 glReadPixels 不会读到半帧。
        glFinish();
        ok = ok && checkGl("draw", error);
    }

    if (ok) {
        // ---------- 回读 ----------
        output.width = input.width;
        output.height = input.height;
        output.pixels.resize(static_cast<std::size_t>(input.width) * input.height * 4u);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        // glReadPixels：从当前 READ 帧缓冲的 (0,0) 起，读 width×height 个像素。
        // GL_RGBA + GL_UNSIGNED_BYTE：每个像素 4 字节，顺序 R,G,B,A，数值 0..255。
        // OpenGL 的原点在左下；本桥协议约定第 0 行是图像顶部，调用方在写文件前已按该约定组好输入。
        glReadPixels(0, 0, static_cast<GLsizei>(input.width),
                     static_cast<GLsizei>(input.height), GL_RGBA,
                     GL_UNSIGNED_BYTE, output.pixels.data());
        ok = ok && checkGl("glReadPixels", error);
    }

    // 解绑并删除本次资源。程序和 VAO 留给下一次 render。
    glBindFramebuffer(GL_FRAMEBUFFER, 0);  // 0 表示回到窗口默认帧缓冲。
    glBindVertexArray(0);
    glUseProgram(0);
    if (obj.fbo) glDeleteFramebuffers(1, &obj.fbo);
    if (obj.colorTexture) glDeleteTextures(1, &obj.colorTexture);
    if (obj.lutTexture) glDeleteTextures(1, &obj.lutTexture);
    if (obj.inputTexture) glDeleteTextures(1, &obj.inputTexture);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);

    if (!ok) output = RgbaImage{};
    return ok;
}

// 【模块功能】按依赖顺序释放 GPU 对象，再拆窗口。析构和 init 失败都会走到这里。
void GlRenderer::shutdown() {
    if (initialized_ || program_ != 0) {
        if (program_ != 0) {
            glDeleteProgram(program_);
            program_ = 0;
        }
        if (vao_ != 0) {
            glDeleteVertexArrays(1, &vao_);
            vao_ = 0;
        }
        glUseProgram(0);
        glBindVertexArray(0);
    }
    initialized_ = false;
    releaseGl();
}

// 【模块功能】销毁隐藏窗口并终止 GLFW。必须在 GL 对象删除之后调用，否则上下文先没了，删除调用会失效。
void GlRenderer::releaseGl() {
    if (window_ != nullptr) {
        glfwDestroyWindow(static_cast<GLFWwindow*>(window_));
        window_ = nullptr;
    }
    if (glfwReady_) {
        glfwTerminate();
        glfwReady_ = false;
    }
}
