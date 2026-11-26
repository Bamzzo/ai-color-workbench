# 第三方组件、来源与许可（P0 本机）

本文件记录本机实际使用的组件，不代表已做发布打包或法律审查。DLL 不随源码仓库
提交，只存在于本机构建目录。

| 组件 | 版本 / 来源 | 许可 | 用途 |
| --- | --- | --- | --- |
| GLAD | 0.1.34，`glad.c` 由 [glad.dav1d.de](https://glad.dav1d.de/) 生成，GL 3.3 core | MIT / 生成的加载器代码 | OpenGL 函数加载 |
| GLFW | 3.5.1，vcpkg `arm64-windows-static-md` | zlib/libpng（上游） | 隐藏窗口与 GL 上下文 |
| Mesa | 24.3.4，`gl_test/mesa_extract/opengl32.dll` | MIT | ARM64 软件 OpenGL |
| DirectX Shader Compiler | `dxil.dll`（随 Mesa 提取目录） | MIT | Mesa D3D12 后端 |
| Pillow | 13.0.0（锁定） | HPND | 图像解码/编码、ICC |
| numpy | 2.5.4（锁定） | BSD-3-Clause | 数值计算 |
| jsonschema | 4.26.0（锁定） | MIT | ColorParams 校验 |
| httpx | 0.28.1（锁定） | BSD-3-Clause | AI HTTP 客户端 |
| python-dotenv | 1.2.4（锁定） | BSD-3-Clause | `.env` 加载 |
| Python | 3.13.12 | PSF-2.0 | 运行时 |

## Mesa DLL 校验值

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `build-arm64/Debug/opengl32.dll` | 12,940,800 | `E63D667BCB8ABDEFFF909252A1265EE9B0132DEF46015832A37D20F6AA2D6D4A` |
| `build-arm64/Debug/dxil.dll` | 2,903,088 | `4332A704F0577E0F76F94811F03801482B8EEDED04FC816BCD0DACB54052056D` |

这两个文件来自课程工作区既有的 `gl_test/mesa_extract`，未从网络重新下载。若换机器
或换 DLL，必须重新记录版本、许可与哈希后再声明可复现。
