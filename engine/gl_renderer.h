// ============================================================================
// 【文件总体作用】
//   离屏调色引擎的对外接口。GlRenderer 在调用线程上创建隐藏的 OpenGL 3.3
//   上下文，把一张直通 RGBA8 原图和一份 3D LUT 送进 GPU，再把调色结果读回内存。
//   它只做“查表 + 强度混合”，不解释曝光、色温等调色参数（那些已烘焙进 LUT）。
//
// 【输入与输出】
//   输入：shader 目录（fullscreen.vert / grade.frag）、RgbaImage、CubeLut、强度 [0,1]。
//   输出：同样尺寸的 RgbaImage（编码域 sRGB 进、编码域 sRGB 出，Alpha 原样拷贝），
//         以及失败时写入 error 的人类可读原因。
//
// 【核心技术点】
//   GLFW 隐藏窗口、GLAD 加载函数指针、着色器编译链接、
//   2D 原图纹理与 3D LUT 浮点纹理、自定义 FBO、glDrawArrays、glReadPixels。
// ============================================================================
#pragma once

#include <string>

#include "cube.h"
#include "rgba_bridge.h"

// 隐藏窗口上的 OpenGL 3.3 渲染器。
// 初始化、绘制、销毁全部发生在调用它的那一条线程（本进程里就是主线程）。
// OpenGL 上下文不能跨线程使用，所以这里不设后台渲染线程。
class GlRenderer {
public:
    GlRenderer() = default;
    ~GlRenderer();

    // 上下文和 GPU 资源不可复制：拷贝会让两个对象争同一份 GL 名字。
    GlRenderer(const GlRenderer&) = delete;
    GlRenderer& operator=(const GlRenderer&) = delete;

    // 创建隐藏上下文并编译链接着色器程序。成功后可反复调用 render。
    bool init(const std::string& shaderDir, std::string& error);
    // 删除程序与 VAO，并销毁 GLFW 窗口与库状态。
    void shutdown();

    // 编码域 sRGB 进、编码域 sRGB 出。Alpha 按字节原样拷贝，不参与查表。
    bool render(const RgbaImage& input, const CubeLut& lut, float strength,
                RgbaImage& output, std::string& error);

    // 形如 "版本 | 渲染器 | 厂商"，便于日志和答辩时确认实际落到哪块 GPU。
    std::string glInfo() const { return glInfo_; }

private:
    // 创建 64×64 不可见窗口，加载 GLAD，查询版本与纹理尺寸上限。
    bool initGlfw(std::string& error);
    // 读取并编译 fullscreen.vert / grade.frag，链成一个程序对象。
    bool loadProgram(const std::string& shaderDir, std::string& error);
    // 只释放窗口和 GLFW，不碰已经删掉的着色器对象。
    void releaseGl();

    bool initialized_ = false;
    bool glfwReady_ = false;
    void* window_ = nullptr;  // 实际类型是 GLFWwindow*；头文件不暴露 GLFW，避免把窗口库泄漏给调用方。
    unsigned int program_ = 0;  // 链接好的着色器程序名字（GLuint）。
    unsigned int vao_ = 0;      // 空顶点数组对象。Core Profile 绘制前必须绑定 VAO，即使不用 VBO。
    int maxTextureSize_ = 0;    // GL_MAX_TEXTURE_SIZE，2D 原图单边上限。
    int max3dTextureSize_ = 0;  // GL_MAX_3D_TEXTURE_SIZE，LUT 单边上限。
    std::string glInfo_;
};
