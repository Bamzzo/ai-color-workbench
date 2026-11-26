#define NOMINMAX
#define GLFW_INCLUDE_NONE
#include <glad/glad.h>
#include <GLFW/glfw3.h>
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Image { int w=0, h=0; std::vector<unsigned char> rgb; };
struct Lut { int size=0; float dmin[3]{0,0,0}; float dmax[3]{1,1,1}; std::vector<float> rgb; };

static void fail(const std::string& s) { throw std::runtime_error(s); }
static std::string readText(const char* p) { std::ifstream f(p); if(!f) fail(std::string("无法读取 ")+p); std::stringstream ss; ss<<f.rdbuf(); return ss.str(); }

static Image makeTestImage() {
    Image im; im.w=4; im.h=2; im.rgb={255,0,0, 0,255,0, 0,0,255, 255,255,255, 32,64,96, 96,64,32, 160,96,32, 220,180,80}; return im;
}
static Image readPPM(const char* path) {
    std::ifstream f(path, std::ios::binary); if(!f) fail(std::string("无法读取图片 ")+path);
    std::string magic; int w=0,h=0,maxv=0; f>>magic>>w>>h>>maxv; if(magic!="P6"||w<=0||h<=0||maxv!=255) fail("当前原型只支持 P6 PPM (8-bit)"); f.get();
    Image im; im.w=w; im.h=h; im.rgb.resize(static_cast<size_t>(w)*h*3); f.read(reinterpret_cast<char*>(im.rgb.data()), im.rgb.size()); if(!f) fail("PPM 数据不完整"); return im;
}
static void writePPM(const char* path, const Image& im) { std::ofstream f(path,std::ios::binary); f<<"P6\n"<<im.w<<' '<<im.h<<"\n255\n"; f.write(reinterpret_cast<const char*>(im.rgb.data()), im.rgb.size()); }

static Lut makeLut(const std::string& kind, int n=17) {
    Lut l; l.size=n; l.rgb.resize(static_cast<size_t>(n)*n*n*3);
    for(int b=0;b<n;++b) for(int g=0;g<n;++g) for(int r=0;r<n;++r) {
        float x=float(r)/(n-1), y=float(g)/(n-1), z=float(b)/(n-1); float o[3]={x,y,z};
        if(kind=="black") o[0]=o[1]=o[2]=0; else if(kind=="red") o[0]=1,o[1]=o[2]=0; else if(kind=="swap-rb") std::swap(o[0],o[2]);
        size_t i=(static_cast<size_t>(b)*n*n+static_cast<size_t>(g)*n+r)*3; l.rgb[i]=o[0]; l.rgb[i+1]=o[1]; l.rgb[i+2]=o[2];
    } return l;
}
static Lut readCube(const char* path) {
    std::ifstream f(path); if(!f) fail(std::string("无法读取 LUT ")+path); Lut l; std::string line; size_t expected=0;
    while(std::getline(f,line)) { auto p=line.find('#'); if(p!=std::string::npos) line.resize(p); std::stringstream s(line); std::string key; if(!(s>>key)) continue;
        if(key=="TITLE") continue;
        if(key=="LUT_3D_SIZE") { if(!(s>>l.size)||l.size<2||l.size>65) fail("无效 LUT_3D_SIZE"); expected=static_cast<size_t>(l.size)*l.size*l.size*3; }
        else if(key=="DOMAIN_MIN") { if(!(s>>l.dmin[0]>>l.dmin[1]>>l.dmin[2])) fail("无效 DOMAIN_MIN"); }
        else if(key=="DOMAIN_MAX") { if(!(s>>l.dmax[0]>>l.dmax[1]>>l.dmax[2])) fail("无效 DOMAIN_MAX"); }
        else if(key=="LUT_1D_SIZE") fail("不支持 LUT_1D_SIZE");
        else { float a,b,c; std::stringstream d(line); if(!(d>>a>>b>>c)) fail("不支持的 .cube 行: "+line); l.rgb.push_back(a); l.rgb.push_back(b); l.rgb.push_back(c); }
    }
    if(l.size==0) fail("缺少 LUT_3D_SIZE"); if(l.rgb.size()!=expected) fail("LUT 数据行数与尺寸不匹配"); return l;
}

static GLuint shader(GLenum type,const char* src) { GLuint s=glCreateShader(type); glShaderSource(s,1,&src,nullptr); glCompileShader(s); GLint ok=0; glGetShaderiv(s,GL_COMPILE_STATUS,&ok); if(!ok){char log[2048];glGetShaderInfoLog(s,2048,nullptr,log);fail(log);} return s; }
static GLuint program() { const char* vs="#version 330 core\nout vec2 uv; const vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3)); void main(){gl_Position=vec4(p[gl_VertexID],0,1); uv=0.5*(p[gl_VertexID]+1.0);}"; const char* fs="#version 330 core\nin vec2 uv; out vec4 frag; uniform sampler2D uImage; uniform sampler3D uLut; uniform vec3 uMin,uMax; void main(){vec3 c=texture(uImage,uv).rgb; vec3 q=(c-uMin)/(uMax-uMin); frag=vec4(texture(uLut,clamp(q,0.0,1.0)).rgb,1.0);}"; GLuint v=shader(GL_VERTEX_SHADER,vs), f=shader(GL_FRAGMENT_SHADER,fs), p=glCreateProgram(); glAttachShader(p,v);glAttachShader(p,f);glLinkProgram(p); GLint ok=0;glGetProgramiv(p,GL_LINK_STATUS,&ok);if(!ok)fail("shader link failed");glDeleteShader(v);glDeleteShader(f);return p; }

static Image render(const Image& im,const Lut& lut) {
    GLuint ti=0,tl=0,fbo=0,out=0; glPixelStorei(GL_UNPACK_ALIGNMENT,1); glGenTextures(1,&ti);glBindTexture(GL_TEXTURE_2D,ti);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexImage2D(GL_TEXTURE_2D,0,GL_RGB8,im.w,im.h,0,GL_RGB,GL_UNSIGNED_BYTE,im.rgb.data());
    glGenTextures(1,&tl);glBindTexture(GL_TEXTURE_3D,tl);glTexParameteri(GL_TEXTURE_3D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_3D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_3D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_3D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_3D,GL_TEXTURE_WRAP_R,GL_CLAMP_TO_EDGE);glTexImage3D(GL_TEXTURE_3D,0,GL_RGB32F,lut.size,lut.size,lut.size,0,GL_RGB,GL_FLOAT,lut.rgb.data());
    glGenTextures(1,&out);glBindTexture(GL_TEXTURE_2D,out);glTexImage2D(GL_TEXTURE_2D,0,GL_RGB8,im.w,im.h,0,GL_RGB,GL_UNSIGNED_BYTE,nullptr);glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,out,0);if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)fail("FBO 不完整");
    GLuint vao=0; glGenVertexArrays(1,&vao); glBindVertexArray(vao); GLuint p=program();glViewport(0,0,im.w,im.h);glUseProgram(p);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,ti);glUniform1i(glGetUniformLocation(p,"uImage"),0);glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_3D,tl);glUniform1i(glGetUniformLocation(p,"uLut"),1);glUniform3f(glGetUniformLocation(p,"uMin"),lut.dmin[0],lut.dmin[1],lut.dmin[2]);glUniform3f(glGetUniformLocation(p,"uMax"),lut.dmax[0],lut.dmax[1],lut.dmax[2]);glDrawArrays(GL_TRIANGLES,0,3);glFinish();
    Image result=im;result.rgb.resize(static_cast<size_t>(im.w)*im.h*3);glPixelStorei(GL_PACK_ALIGNMENT,1);glReadPixels(0,0,im.w,im.h,GL_RGB,GL_UNSIGNED_BYTE,result.rgb.data());
    glDeleteVertexArrays(1,&vao); glDeleteProgram(p);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&out);glDeleteTextures(1,&tl);glDeleteTextures(1,&ti);glBindFramebuffer(GL_FRAMEBUFFER,0);return result;
}
static int maxDev(const Image&a,const Image&b){int m=0;for(size_t i=0;i<a.rgb.size();++i)m=std::max(m,std::abs(int(a.rgb[i])-int(b.rgb[i])));return m;}
int main(int argc,char** argv){try{std::string lutKind="identity", input=""; for(int i=1;i<argc;++i){std::string a=argv[i];if(a=="--lut"&&i+1<argc)lutKind=argv[++i];else if(a=="--input"&&i+1<argc)input=argv[++i];else if(a=="--cube"&&i+1<argc)lutKind=argv[++i];}
    if(!glfwInit())fail("GLFW 初始化失败"); glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);GLFWwindow*w=glfwCreateWindow(64,64,"ai_color_app",nullptr,nullptr);if(!w)fail("窗口创建失败");glfwMakeContextCurrent(w);if(!gladLoadGLLoader((GLADloadproc)glfwGetProcAddress))fail("GLAD 加载失败");printf("OpenGL %s | %s\n",glGetString(GL_VERSION),glGetString(GL_RENDERER)); Image im=input.empty()?makeTestImage():readPPM(input.c_str()); Lut l=(lutKind=="identity"||lutKind=="black"||lutKind=="red"||lutKind=="swap-rb")?makeLut(lutKind):readCube(lutKind.c_str()); Image out=render(im,l); writePPM("ai_color_output.ppm",out); Image expected=im; if(lutKind=="swap-rb"){for(size_t i=0;i<expected.rgb.size();i+=3) std::swap(expected.rgb[i],expected.rgb[i+2]);} int dev=maxDev(expected,out); printf("PASS image=%dx%d lut=%s max_dev=%d output=ai_color_output.ppm\n",im.w,im.h,lutKind.c_str(),dev); if((lutKind=="identity"||lutKind=="swap-rb") && dev>12) fail("已知 LUT 自检误差超过阈值"); fflush(stdout);ExitProcess(0);
} catch(const std::exception&e){fprintf(stderr,"FAIL: %s\n",e.what());ExitProcess(1);}}










