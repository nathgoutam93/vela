// Win32 support for the clang/MinGW C profile. Paths and process arguments are UTF-8.
#ifndef VELA_WINDOWS_H
#define VELA_WINDOWS_H
#define WIN32_LEAN_AND_MEAN
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <io.h>
#include <direct.h>
#include <process.h>
#include <wchar.h>
static wchar_t *win_wide(const char *s) {
    int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,NULL,0);
    if (!n) { errno=EINVAL; return NULL; }
    wchar_t *out=vela_alloc((size_t)n*sizeof(wchar_t));
    if (!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,out,n)) { free(out); errno=EINVAL; return NULL; }
    return out;
}
static char *win_utf8_text(const wchar_t *s) {
    int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,s,-1,NULL,0,NULL,NULL);
    if (!n) { errno=EINVAL; return NULL; }
    char *out=vela_alloc((size_t)n);
    if (!WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,s,-1,out,n,NULL,NULL)) { free(out); errno=EINVAL; return NULL; }
    return out;
}
static char *win_utf8(const wchar_t *s) {
    char *out=win_utf8_text(s);if(!out)return NULL;
    for(char *p=out;*p;p++)if(*p=='\\')*p='/';
    return out;
}
static char *win_env_text(const char *name) {
    wchar_t *wide=win_wide(name);if(!wide)return NULL;
    SetLastError(ERROR_SUCCESS);DWORD needed=GetEnvironmentVariableW(wide,NULL,0);
    if(!needed && GetLastError()==ERROR_ENVVAR_NOT_FOUND){free(wide);return NULL;}
    wchar_t *buffer=vela_alloc(((size_t)needed+1)*sizeof(wchar_t));
    DWORD got=GetEnvironmentVariableW(wide,buffer,needed+1);free(wide);
    if(got>needed){free(buffer);return NULL;}
    buffer[got]=0;char *text=win_utf8_text(buffer);free(buffer);return text;
}
static void win_errno(DWORD code) {
    errno=code==ERROR_FILE_NOT_FOUND || code==ERROR_PATH_NOT_FOUND?ENOENT:
          code==ERROR_ACCESS_DENIED?EACCES:code==ERROR_ALREADY_EXISTS || code==ERROR_FILE_EXISTS?EEXIST:
          code==ERROR_NOT_ENOUGH_MEMORY?ENOMEM:code==ERROR_DIRECTORY?ENOTDIR:EIO;
}
static char *win_resolved_path(const wchar_t *path) {
    HANDLE handle=CreateFileW(path,0,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,NULL,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,NULL);
    if(handle==INVALID_HANDLE_VALUE){win_errno(GetLastError());return NULL;}
    DWORD length=GetFinalPathNameByHandleW(handle,NULL,0,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    if(!length){DWORD code=GetLastError();CloseHandle(handle);win_errno(code);return NULL;}
    wchar_t *buffer=vela_alloc(((size_t)length+1)*sizeof(wchar_t));
    DWORD got=GetFinalPathNameByHandleW(handle,buffer,length+1,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    DWORD code=GetLastError();CloseHandle(handle);
    if(!got||got>length){free(buffer);win_errno(code);return NULL;}
    char *resolved=win_utf8(buffer);free(buffer);if(!resolved)return NULL;
    if(!strncmp(resolved,"//?/UNC/",8)){memmove(resolved+2,resolved+8,strlen(resolved+8)+1);resolved[0]=resolved[1]='/';}
    else if(!strncmp(resolved,"//?/",4))memmove(resolved,resolved+4,strlen(resolved+4)+1);
    return resolved;
}
static FILE *win_fopen(const char *path,const char *mode) {
    wchar_t *p=win_wide(path),*m=win_wide(mode); FILE *f=NULL;
    if(p&&m)f=_wfopen(p,m); free(p);free(m);return f;
}
static int win_remove(const char *path) {
    wchar_t *p=win_wide(path);if(!p)return -1;
    int r=_wremove(p);if(r)r=_wrmdir(p);free(p);return r;
}
static char *win_mkdtemp(char *pattern) {
    static long counter=0;
    size_t n=strlen(pattern);if(n<6){errno=EINVAL;return NULL;}
    for(int attempt=0;attempt<100;attempt++) {
        unsigned long value=(unsigned long)GetTickCount64()^(unsigned long)GetCurrentProcessId()^(unsigned long)InterlockedIncrement(&counter);
        snprintf(pattern+n-6,7,"%06lx",value&0xfffffful);
        wchar_t *p=win_wide(pattern);if(!p)return NULL;
        BOOL ok=CreateDirectoryW(p,NULL);DWORD code=GetLastError();free(p);
        if(ok)return pattern;if(code!=ERROR_ALREADY_EXISTS){win_errno(code);return NULL;}
    }
    errno=EEXIST;return NULL;
}
#define fopen win_fopen
#define remove win_remove
#define mkdtemp win_mkdtemp
#define flockfile _lock_file
#define funlockfile _unlock_file
#define putc_unlocked _putc_nolock
#define getc_unlocked _getc_nolock
#endif
