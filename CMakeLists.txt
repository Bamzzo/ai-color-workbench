cmake_minimum_required(VERSION 3.20)

# C is required so glad.c is compiled (the VS generator otherwise treats it as
# a non-buildable item and the GL loader symbols are missing at link time).
project(ai_color_app C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(ENGINE_SOURCES
  engine/main.cpp
  engine/json_lite.cpp
  engine/cube.cpp
  engine/rgba_bridge.cpp
  engine/gl_renderer.cpp
  glad.c)

find_package(glfw3 CONFIG REQUIRED)

set(GLAD_INCLUDE_DIR "" CACHE PATH "Directory containing glad/glad.h")
if(NOT EXISTS "${GLAD_INCLUDE_DIR}/glad/glad.h")
  message(FATAL_ERROR
    "Set GLAD_INCLUDE_DIR to the directory containing glad/glad.h")
endif()

add_executable(render_worker ${ENGINE_SOURCES})
target_link_libraries(render_worker PRIVATE glfw)
target_include_directories(render_worker PRIVATE "${GLAD_INCLUDE_DIR}")

# Shaders are copied next to the executable; the worker resolves
# <exe-dir>/shaders by default and accepts --shaders for tests.
add_custom_command(TARGET render_worker POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory
    $<TARGET_FILE_DIR:render_worker>/shaders
  COMMAND ${CMAKE_COMMAND} -E copy_directory
    ${CMAKE_CURRENT_SOURCE_DIR}/shaders
    $<TARGET_FILE_DIR:render_worker>/shaders)

if(MSVC)
  target_compile_options(render_worker PRIVATE /utf-8 /W3)
endif()

# The original single-file prototype (main.cpp) is kept as a historical
# reference and is intentionally not part of the build.
