// M24 launch policy. Installed before user code, including foreign constructors.
#include <sys/resource.h>
#include <limits.h>
#if defined(__APPLE__)
#include <sandbox.h>
#elif defined(__linux__) && defined(__x86_64__)
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <linux/seccomp.h>
#include <linux/filter.h>
#include <linux/audit.h>
#endif
#define CAP_FS 1
#define CAP_OS 2
#define CAP_NET 4
#define CAP_CLOCK 8
#define CAP_UNSAFE 16
#define CAP_SCOPED 32
static unsigned vela_cap_mask=31;
// standalone builds are a trusted workflow
static char **vela_cap_roots=NULL;
static size_t vela_cap_root_count=0;
static char *vela_cap_cwd=NULL;
static _Noreturn void cap_fail(const char *code,const char *why) {
    fprintf(stderr,"vela: %s [%s]\n",why,code);
    fflush(stderr);
    _Exit(126);
}
static unsigned cap_bit(const char *s) {
    if (!strcmp(s,"fs"))return CAP_FS;
    if (!strcmp(s,"os"))return CAP_OS;
    if (!strcmp(s,"net"))return CAP_NET;
    if (!strcmp(s,"clock"))return CAP_CLOCK;
    if (!strcmp(s,"unsafe"))return CAP_UNSAFE;
    return 0;
}
static bool cap_beneath(const char *path,const char *root) {
    size_t n=strlen(root);
    return !strcmp(root,"/") || (!strncmp(path,root,n) && (path[n]==0 || path[n]=='/'));
}
// Existing targets follow real symlinks. For creation, resolve the nearest
// existing parent; the OS policy remains authoritative against rename races.
static char *cap_resolve(const char *input) {
    char *absolute_input=NULL;
    const char *path=input;
    if (input[0]!='/' && vela_cap_cwd) {
        size_t n=strlen(vela_cap_cwd)+strlen(input)+2;
        absolute_input=vela_alloc(n);
        snprintf(absolute_input,n,"%s/%s",vela_cap_cwd,input);
        path=absolute_input;
    }
    char *resolved=realpath(path,NULL);
    if (resolved) {
        free(absolute_input);
        return resolved;
    }
    // Keep the normalized absolute spelling across the missing-parent walk.
    if (absolute_input) {
        char *missing=cap_resolve(absolute_input);
        free(absolute_input);
        return missing;
    }
    if (errno!=ENOENT && errno!=ENOTDIR)return NULL;
    char *absolute;
    if (path[0]=='/')absolute=strdup(path);
    else {
        char *cwd=getcwd(NULL,0);
        if (!cwd)return NULL;
        size_t n=strlen(cwd)+strlen(path)+2;
        absolute=vela_alloc(n);
        snprintf(absolute,n,"%s/%s",cwd,path);
        free(cwd);
    }
    size_t size=strlen(absolute),cut=size;
    while (cut>0) {
        while (cut>0 && absolute[cut-1]!='/')cut--;
        if (!cut)break;
        char saved=absolute[cut];
        absolute[cut]=0;
        resolved=realpath(absolute,NULL);
        absolute[cut]=saved;
        if (resolved)break;
        if (cut==1)break;
        cut--;
    }
    if (!resolved) {
        free(absolute);
        return NULL;
    }
    size_t n=strlen(resolved)+size-cut+2;
    char *joined=vela_alloc(n);
    snprintf(joined,n,"%s/%s",resolved,absolute+cut);
    free(resolved);
    free(absolute);
    // Lexically normalize the unresolved suffix, including .. boundaries.
    char *out=vela_alloc(n);
    size_t used=1;
    out[0]='/';
    char *save=NULL;
    for (char *part=strtok_r(joined,"/",&save); part; part=strtok_r(NULL,"/",&save)) {
        if (!strcmp(part,"."))continue;
        if (!strcmp(part,"..")) {
            while (used>1 && out[used-1]!='/')used--;
            if (used>1)used--;
            continue;
        }
        if (used>1)out[used++]='/';
        size_t len=strlen(part);
        memcpy(out+used,part,len);
        used+=len;
    }
    out[used]=0;
    free(joined);
    return out;
}
bool vela_cap_check(const char *effect,vela_str path,vela_str *error) {
    unsigned bit=cap_bit(effect);
    bool allowed=(vela_cap_mask&bit)!=0;
    if (allowed && bit==CAP_FS && (vela_cap_mask&CAP_SCOPED)) {
        char *raw=c_path(path),*resolved=raw?cap_resolve(raw):NULL;
        free(raw);
        allowed=false;
        if (resolved) {
            for (size_t i=0; i<vela_cap_root_count; i++)if (cap_beneath(resolved,vela_cap_roots[i])) {
                allowed=true;
                break;
            }
            free(resolved);
        }
    }
    if (allowed)return true;
    *error=message("capability denied: ",VELA_STR(effect,(int64_t)strlen(effect))," [E6010]");
    return false;
}
void vela_cap_require(const char *effect) {
    vela_str error=VELA_STR("",0);
    if (!vela_cap_check(effect,VELA_STR("",0),&error)) {
        fflush(stdout);
        fprintf(stderr,"vela: %.*s\n",(int)error.len,(const char*)error.data);
        fflush(stderr);
        _Exit(126);
    }
}
bool vela_cap_process(vela_str *error) {
    if (!vela_cap_check("os",VELA_STR("",0),error) || !vela_cap_check("clock",VELA_STR("",0),error))return false;
#if defined(__APPLE__)
    if (!(vela_cap_mask&CAP_NET))return sys_error(error,"capability denied: macOS deny net also disables external processes to prevent native socket creation [E6010]");
#endif
    return true;
}
bool vela_sys_canonical(vela_str path,vela_str *out,vela_str *error) {
    if (files_faked) {
        lock_fakes();
        bool found=sys_fake_kind(path)!=0;
        if (found) {
            *out=path;
            vela_str_retain(*out);
        }
        unlock_fakes();
        return found || sys_error(error,"fake path does not exist");
    }
    if (!vela_cap_check("fs",path,error))return false;
    char *raw=c_path(path);
    if (!raw)return sys_error(error,"path contains a zero byte");
    char *resolved=realpath(raw,NULL);
    free(raw);
    if (!resolved)return sys_errno(error);
    *out=str_from(resolved,strlen(resolved));
    free(resolved);
    return true;
}
typedef struct {
    unsigned mask;
    char **roots;
    size_t count;
    char *coverage;
    bool explicit_allow[5],explicit_deny[5];
}
cap_policy;
static int cap_index(unsigned bit) {
    for (int i=0; i<5; i++)if (bit==(1u<<i))return i;
    return -1;
}
static bool cap_parse(vela_array *allow,vela_array *deny,cap_policy *p,vela_str *error) {
    memset(p,0,sizeof *p);
    p->mask=15;
    p->roots=vela_alloc(((size_t)allow->len+vela_cap_root_count+1)*sizeof(char*));
    for (int side=0; side<2; side++) {
        vela_array *items=side?deny:allow;
        for (int64_t i=0; i<items->len; i++) {
            char *raw=c_path(sys_word(items,i));
            if (!raw)return sys_error(error,"NUL in capability rule");
            if (!side && !strncmp(raw,"coverage:",9)) {
                if (p->coverage || strchr(raw,'\n') || strchr(raw,'\r')) {
                    free(raw);
                    return sys_error(error,"invalid coverage artifact grant");
                }
                if (!vela_cap_check("fs",VELA_STR(raw+9,(int64_t)strlen(raw+9)),error)) {
                    free(raw);
                    return false;
                }
                p->coverage=realpath(raw+9,NULL);
                free(raw);
                if (!p->coverage)return sys_error(error,"coverage artifact must exist");
                struct stat st;
                if (stat(p->coverage,&st) || !S_ISREG(st.st_mode))return sys_error(error,"coverage artifact must be a regular file");
                continue;
            }
            if (!side && !strncmp(raw,"fs:",3)) {
                if (p->count>=256 || strchr(raw,'\n') || strchr(raw,'\r') || !raw[3]) {
                    free(raw);
                    return sys_error(error,"invalid filesystem root");
                }
                if (!vela_cap_check("fs",VELA_STR(raw+3,(int64_t)strlen(raw+3)),error)) {
                    free(raw);
                    return false;
                }
                char *root=realpath(raw+3,NULL);
                free(raw);
                if (!root)return sys_error(error,"filesystem roots must exist and be resolvable");
                struct stat st;
                if (stat(root,&st) || (!S_ISDIR(st.st_mode) && !S_ISREG(st.st_mode))) {
                    free(root);
                    return sys_error(error,"filesystem roots must be directories or regular files");
                }
                if (strchr(root,'\n') || strchr(root,'\r')) {
                    free(root);
                    return sys_error(error,"newline in filesystem root");
                }
                p->roots[p->count++]=root;
                p->mask|=CAP_SCOPED;
                continue;
            }
            unsigned bit=cap_bit(raw);
            free(raw);
            if (!bit)return sys_error(error,"unknown capability; use fs[:PATH], os, net, clock or unsafe");
            int ix=cap_index(bit);
            if (side)p->explicit_deny[ix]=true;
            else p->explicit_allow[ix]=true;
        }
    }
    for (int i=0; i<5; i++) {
        unsigned bit=1u<<i;
        if (p->explicit_allow[i])p->mask|=bit;
        if (p->explicit_deny[i])p->mask&=~bit;
    }
    if (p->count && p->explicit_allow[0])return sys_error(error,"bare fs and fs:PATH grants cannot be combined");
    for (int i=0; i<4; i++)if (p->explicit_allow[i] && !(vela_cap_mask&(1u<<i)))return sys_error(error,"cannot widen an inherited capability denial");
    p->mask=(p->mask&~15u)|(p->mask&vela_cap_mask&15u);
    if ((p->mask&CAP_FS) && (vela_cap_mask&CAP_SCOPED)) {
        if (p->explicit_allow[0])return sys_error(error,"cannot widen inherited filesystem roots");
        if (!p->count)for (size_t i=0; i<vela_cap_root_count; i++)p->roots[p->count++]=strdup(vela_cap_roots[i]);
        p->mask|=CAP_SCOPED;
    }
    if ((p->mask&CAP_UNSAFE) && (!(p->mask&CAP_CLOCK) || !(p->mask&CAP_OS)))return sys_error(error,"unsafe cannot be combined with clock or os denial on this profile");
#if defined(__APPLE__)
    if ((p->mask&CAP_UNSAFE) && !(p->mask&CAP_NET))return sys_error(error,"macOS cannot deny C socket descriptor creation; unsafe + deny net is unsupported (use Linux)");
#endif
    return true;
}
static void cap_drop(cap_policy *p) {
    for (size_t i=0; i<p->count; i++)free(p->roots[i]);
    free(p->roots);
    free(p->coverage);
}
static void cap_export(cap_policy *p) {
    char number[32];
    snprintf(number,sizeof number,"%u",p->mask);
    if (setenv("VELA_CAP_MASK",number,1))cap_fail("E6011","cannot export capability policy");
    char *cwd=getcwd(NULL,0);
    if (!cwd || setenv("VELA_CAP_CWD",cwd,1))cap_fail("E6011","cannot export working directory");
    free(cwd);
    size_t n=1;
    for (size_t i=0; i<p->count; i++)n+=strlen(p->roots[i])+1;
    char *roots=vela_alloc(n),*at=roots;
    for (size_t i=0; i<p->count; i++) {
        size_t len=strlen(p->roots[i]);
        memcpy(at,p->roots[i],len);
        at+=len;
        *at++='\n';
    }
    *at=0;
    if (setenv("VELA_CAP_ROOTS",roots,1))cap_fail("E6011","cannot export filesystem roots");
    free(roots);
}
static void cap_close_fds(bool no_net) {
    if (no_net)for (int fd=0; fd<3; fd++) {
        int type;
        socklen_t n=sizeof type;
        if (!getsockopt(fd,SOL_SOCKET,SO_TYPE,&type,&n))cap_fail("E6011","network-backed standard descriptors are incompatible with deny net");
    }
#if defined(__linux__) && defined(__NR_close_range)
    if (syscall(__NR_close_range,3u,~0u,0)==0)return;
#endif
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE,&limit))cap_fail("E6011","cannot close inherited descriptors");
    for (rlim_t fd=3; fd<limit.rlim_cur; fd++)close((int)fd);
}
#if defined(__APPLE__)
static void cap_profile_literal(vela_array *b,const char *s) {
    uint8_t quote='"';
    vela_array_push(b,&quote);
    for (const unsigned char *p=(const unsigned char*)s; *p; p++) {
        if (*p=='"' || *p=='\\') {
            uint8_t slash='\\';
            vela_array_push(b,&slash);
        }
        vela_array_push(b,p);
    }
    vela_array_push(b,&quote);
}
static void cap_profile_add(vela_array *b,const char *s) {
    for (const uint8_t *p=(const uint8_t*)s; *p; p++)vela_array_push(b,p);
}
static void cap_mac(cap_policy *p,const char *exe) {
    vela_array *b=vela_array_new(&vela_type_byte,1024);
    cap_profile_add(b,"(version 1)\n(allow default)\n(deny mach-priv*)\n(deny process-info*)\n(deny mach-lookup)\n(deny mach-register)\n");
    if (!(p->mask&CAP_NET))cap_profile_add(b,"(deny network*)\n(deny system-socket)\n");
    if (!(p->mask&CAP_OS) || !(p->mask&CAP_CLOCK) || !(p->mask&CAP_NET)) {
        cap_profile_add(b,"(deny process-fork)\n(deny process-exec)\n(allow process-exec (literal ");
        cap_profile_literal(b,exe);
        cap_profile_add(b,"))\n");
    }
    if (!(p->mask&CAP_FS) || (p->mask&CAP_SCOPED)) {
        cap_profile_add(b,"(deny file-read*)\n(deny file-write*)\n(allow file-read* (literal ");
        cap_profile_literal(b,exe);
        cap_profile_add(b,") (subpath \"/System/Library\") (subpath \"/usr/lib\") (subpath \"/private/var/db/dyld\") (literal \"/dev/null\") (literal \"/dev/urandom\"))\n");
        cap_profile_add(b,"(allow file-read-metadata (literal \"/\") (literal \"/System\") (literal \"/usr\") (literal \"/private\") (literal \"/private/var\") (literal \"/private/var/db\") (literal \"/var\") (literal \"/tmp\") (literal \"/etc\"))\n");
        if ((p->mask&CAP_OS) && (p->mask&CAP_CLOCK) && (p->mask&CAP_NET))cap_profile_add(b,"(allow file-read* (subpath \"/bin\") (subpath \"/usr/bin\"))\n");
        cap_profile_add(b,"(import \"/System/Library/Sandbox/Profiles/dyld-support.sb\")\n");
        // Apple Clang's instrumented executables load their trusted sanitizer
        // runtime from the toolchain resource directory, outside /usr/lib.
        cap_profile_add(b,"(allow file-read* (subpath \"/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/clang\") (subpath \"/Library/Developer/CommandLineTools/usr/lib/clang\"))\n");
        cap_profile_add(b,"(allow file-read* (path-ancestors ");
        cap_profile_literal(b,exe);
        cap_profile_add(b,"))\n");
        if (p->mask&CAP_FS)for (size_t i=0; i<p->count; i++) {
            cap_profile_add(b,"(allow file-read* file-write* (subpath ");
            cap_profile_literal(b,p->roots[i]);
            cap_profile_add(b,"))\n");
            cap_profile_add(b,"(allow file-read-metadata (path-ancestors ");
            cap_profile_literal(b,p->roots[i]);
            cap_profile_add(b,"))\n");
        }
    }
    if (p->coverage) {
        cap_profile_add(b,"(allow file-write* file-read-metadata (literal ");
        cap_profile_literal(b,p->coverage);
        cap_profile_add(b,"))\n");
    }
    uint8_t zero=0;
    vela_array_push(b,&zero);
    char *error=NULL;
    int result;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    result=sandbox_init((const char*)b->data,0,&error);
    if (result) {
        fprintf(stderr,"vela: OS sandbox setup failed: %s [E6011]\n",error?error:"unavailable");
        if (error)sandbox_free_error(error);
        _Exit(126);
    }
    vela_array_release(b);
#pragma clang diagnostic pop
}
#elif defined(__linux__) && defined(__x86_64__)
#ifndef __NR_landlock_create_ruleset
#define __NR_landlock_create_ruleset 444
#define __NR_landlock_add_rule 445
#define __NR_landlock_restrict_self 446
#endif
struct cap_landlock_ruleset {
    uint64_t handled_access_fs;
};
struct cap_landlock_path {
    uint64_t allowed_access;
    int32_t parent_fd;
}
__attribute__((packed));
#define CAP_LL_ALL ((1ull<<15)-1)
#define CAP_LL_READ ((1ull<<0)|(1ull<<2)|(1ull<<3))
static bool cap_landlock_rule(int rules,const char *path,uint64_t access,bool optional) {
    int fd=open(path,O_PATH|O_CLOEXEC);
    if (fd<0)return optional && errno==ENOENT;
    struct stat st;
    if (fstat(fd,&st)) {
        close(fd);
        return false;
    }
    if (!S_ISDIR(st.st_mode))access&=(1ull<<0)|(1ull<<1)|(1ull<<2)|(1ull<<14);
    struct cap_landlock_path rule= {
        access,fd
    };
    int result=(int)syscall(__NR_landlock_add_rule,rules,1,&rule,0);
    close(fd);
    return result==0;
}
static void cap_linux_files(cap_policy *p,const char *exe) {
    if ((p->mask&CAP_FS) && !(p->mask&CAP_SCOPED))return;
    long abi=syscall(__NR_landlock_create_ruleset,NULL,0,1);
    if (abi<3)cap_fail("E6011","filesystem restrictions require Linux Landlock ABI 3 or newer");
    struct cap_landlock_ruleset attr= {
        CAP_LL_ALL
    };
    int fd=(int)syscall(__NR_landlock_create_ruleset,&attr,sizeof attr,0);
    if (fd<0)cap_fail("E6011","Landlock ruleset creation failed");
    if (!cap_landlock_rule(fd,exe,CAP_LL_READ,false))cap_fail("E6011","cannot grant executable bootstrap access");
    const char *bootstrap[]= {
        "/usr/lib","/lib","/lib64","/bin","/usr/bin","/etc/ld.so.cache","/dev/null","/dev/urandom"
    };
    for (size_t i=0; i<sizeof bootstrap/sizeof *bootstrap; i++)if (!cap_landlock_rule(fd,bootstrap[i],CAP_LL_READ,true))cap_fail("E6011","cannot grant runtime bootstrap access");
    if (p->mask&CAP_FS)for (size_t i=0; i<p->count; i++)if (!cap_landlock_rule(fd,p->roots[i],CAP_LL_ALL,false))cap_fail("E6011","cannot grant filesystem root");
    if (p->coverage && !cap_landlock_rule(fd,p->coverage,(1ull<<1)|(1ull<<2)|(1ull<<14),false))cap_fail("E6011","cannot grant coverage artifact");
    if (syscall(__NR_landlock_restrict_self,fd,0))cap_fail("E6011","Landlock enforcement failed");
    close(fd);
}
static void cap_filter_deny(struct sock_filter *filter,size_t *n,int nr) {
    filter[(*n)++]=(struct sock_filter)BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,(uint32_t)nr,0,1);
    filter[(*n)++]=(struct sock_filter)BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM);
}
static void cap_linux(cap_policy *p,const char *exe) {
    if (prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0))cap_fail("E6011","no_new_privs setup failed");
    cap_linux_files(p,exe);
    struct sock_filter f[192];
    size_t n=0;
    f[n++]=(struct sock_filter)BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,arch));
    f[n++]=(struct sock_filter)BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,AUDIT_ARCH_X86_64,1,0);
    f[n++]=(struct sock_filter)BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
    f[n++]=(struct sock_filter)BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr));
    f[n++]=(struct sock_filter)BPF_JUMP(BPF_JMP|BPF_JGE|BPF_K,0x40000000u,0,1);
    f[n++]=(struct sock_filter)BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS);
    // Prevent injection into an unsandboxed peer or asynchronous syscall bypass.
    const int always[]= {
        __NR_ptrace,__NR_process_vm_writev,__NR_process_vm_readv,
#ifdef __NR_io_uring_setup
        __NR_io_uring_setup,
#endif
#ifdef __NR_pidfd_getfd
        __NR_pidfd_getfd,
#endif
    };
    for (size_t i=0; i<sizeof always/sizeof *always; i++)cap_filter_deny(f,&n,always[i]);
    if (!(p->mask&CAP_NET)) {
        const int calls[]= {
            __NR_socket,__NR_socketpair,__NR_connect,__NR_bind,__NR_listen,__NR_accept,__NR_accept4,__NR_sendto,__NR_recvfrom,__NR_sendmsg,__NR_recvmsg,__NR_sendmmsg,__NR_recvmmsg
        };
        for (size_t i=0; i<sizeof calls/sizeof *calls; i++)cap_filter_deny(f,&n,calls[i]);
    }
    // No arbitrary C is admitted when os/clock is denied. Vela guards reject
    // process creation; clone remains available for structured worker threads.
    f[n++]=(struct sock_filter)BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW);
    struct sock_fprog program= {
        (unsigned short)n,f
    };
    if (prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program))cap_fail("E6011","seccomp enforcement failed");
}
#endif
static void cap_import(void) {
    const char *raw=getenv("VELA_CAP_MASK");
    if (!raw)return;
    char *end=NULL;
    errno=0;
    unsigned long mask=strtoul(raw,&end,10);
    if (errno || !*raw || !end || *end || mask>63)cap_fail("E6011","invalid inherited capability mask");
    vela_cap_mask=(unsigned)mask;
    const char *cwd=getenv("VELA_CAP_CWD");
    if (!cwd || cwd[0]!='/')cap_fail("E6011","invalid inherited working directory");
    vela_cap_cwd=strdup(cwd);
    const char *roots=getenv("VELA_CAP_ROOTS");
    if (!roots)roots="";
    char *copy=strdup(roots),*save=NULL;
    size_t cap=1;
    for (const char *p=roots; *p; p++)if (*p=='\n')cap++;
    vela_cap_roots=vela_alloc(cap*sizeof(char*));
    for (char *root=strtok_r(copy,"\n",&save); root; root=strtok_r(NULL,"\n",&save)) {
        if (root[0]!='/')cap_fail("E6011","invalid inherited filesystem root");
        vela_cap_roots[vela_cap_root_count++]=strdup(root);
    }
    free(copy);
    if ((vela_cap_mask&CAP_SCOPED) && !vela_cap_root_count)cap_fail("E6011","missing inherited filesystem roots");
}
void vela_policy_init(int argc,char **argv) {
    cap_import();
    const char *launch=getenv("VELA_POLICY_LAUNCH");
    if (!launch || strcmp(launch,"1") || argc<2 || strcmp(argv[1],"--vela-exec-policy-v1"))return;
    unsetenv("VELA_POLICY_LAUNCH");
    vela_cap_require("os");
    vela_cap_require("clock");
    int at=2;
    vela_array *lists[2]= {
        vela_array_new(&vela_type_str,8),vela_array_new(&vela_type_str,8)
    };
    for (int side=0; side<2; side++) {
        if (at>=argc)cap_fail("E6011","truncated launch policy");
        char *end=NULL;
        long count=strtol(argv[at++],&end,10);
        if (!end || *end || count<0 || count>1024 || count>argc-at)cap_fail("E6011","invalid launch policy length");
        for (long i=0; i<count; i++) {
            vela_str s=VELA_STR(argv[at],(int64_t)strlen(argv[at]));
            at++;
            vela_array_push(lists[side],&s);
        }
    }
    if (at>=argc || strcmp(argv[at++],"--") || at>=argc)cap_fail("E6011","missing policy executable");
    cap_policy p;
    vela_str error=VELA_STR("",0);
    if (!cap_parse(lists[0],lists[1],&p,&error)) {
        fprintf(stderr,"vela: %.*s [E6011]\n",(int)error.len,(const char*)error.data);
        _Exit(126);
    }
    char *exe=realpath(argv[at],NULL);
    if (!exe)cap_fail("E6011","cannot resolve policy executable");
    cap_export(&p);
    cap_close_fds(!(p.mask&CAP_NET));
    bool kernel=!(p.mask&CAP_NET) || !(p.mask&CAP_FS) || (p.mask&CAP_SCOPED) || !(p.mask&CAP_OS) || !(p.mask&CAP_CLOCK);
    if (kernel) {
#if defined(__APPLE__)
        cap_mac(&p,exe);
#elif defined(__linux__) && defined(__x86_64__)
        cap_linux(&p,exe);
#else
        cap_fail("E6011","OS capability enforcement is unsupported on this platform");
#endif
    }
    execv(exe,argv+at);
    cap_fail("E6011","cannot execute sandboxed program");
}
bool vela_sys_sandbox_run(vela_array *command,vela_array *allow,vela_array *deny,int64_t *out,vela_str *error) {
    bool handled=false;
    bool fake_ok=sys_legacy_process(command,out,error,NULL,&handled);
    if (handled)return fake_ok;
    if (!vela_cap_process(error))return false;
    if (!command->len)return sys_error(error,"sandbox_run needs an executable");
    cap_policy p;
    bool valid=cap_parse(allow,deny,&p,error);
    cap_drop(&p);
    if (!valid)return false;
    vela_array *args=vela_array_new(&vela_type_str,command->len+allow->len+deny->len+5);
    vela_str self=vela_os_executable();
    sys_push(args,self);
    vela_str_release(self);
    sys_push(args,VELA_STR("--vela-exec-policy-v1",21));
    vela_array *lists[2]= {
        allow,deny
    };
    for (int side=0; side<2; side++) {
        vela_str count=vela_from_int(lists[side]->len);
        sys_push(args,count);
        vela_str_release(count);
        for (int64_t i=0; i<lists[side]->len; i++)sys_push(args,sys_word(lists[side],i));
    }
    sys_push(args,VELA_STR("--",2));
    for (int64_t i=0; i<command->len; i++)sys_push(args,sys_word(command,i));
    char **argv=vela_alloc(((size_t)args->len+1)*sizeof(char*));
    int64_t made=0;
    for (; made<args->len; made++) {
        argv[made]=c_path(sys_word(args,made));
        if (!argv[made])break;
    }
    argv[made]=NULL;
    if (made!=args->len) {
        for (int64_t i=0; i<made; i++)free(argv[i]);
        free(argv);
        vela_array_release(args);
        return sys_error(error,"NUL in launch argument");
    }
    size_t env_count=0;
    while (environ[env_count])env_count++;
    char **env=vela_alloc((env_count+2)*sizeof(char*));
    size_t n=0;
    for (size_t i=0; i<env_count; i++)if (strncmp(environ[i],"VELA_POLICY_LAUNCH=",19))env[n++]=environ[i];
    env[n++]="VELA_POLICY_LAUNCH=1";
    env[n]=NULL;
    fflush(stdout);
    fflush(stderr);
    pid_t pid=-1;
    pthread_mutex_lock(&fork_lock);
    int err=posix_spawn(&pid,argv[0],NULL,NULL,argv,env);
    pthread_mutex_unlock(&fork_lock);
    for (int64_t i=0; i<args->len; i++)free(argv[i]);
    free(argv);
    free(env);
    vela_array_release(args);
    if (err) {
        errno=err;
        return sys_errno(error);
    }
    int status=0;
    pid_t waited;
    do {
        waited=waitpid(pid,&status,0);
    }
    while (waited<0 && errno==EINTR);
    if (waited<0)return sys_errno(error);
    *out=WIFSIGNALED(status)?128+WTERMSIG(status):WEXITSTATUS(status);
    return true;
}
// Coverage is active only in the instrumented test harness and only when the
// driver supplies a report path. First hits are serialized across worker tasks.
static pthread_mutex_t coverage_lock=PTHREAD_MUTEX_INITIALIZER;
static uint8_t *coverage_seen=NULL;
static int64_t coverage_count=0;
static int coverage_fd=-1;
void vela_coverage_begin(int argc,char **argv,int64_t count) {
    if (argc<3)return;
    coverage_fd=open(argv[2],O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC,0600);
    if (coverage_fd<0)cap_fail("E6011","cannot open coverage hit report");
    coverage_count=count;
    coverage_seen=calloc((size_t)count+1,1);
    if (!coverage_seen)cap_fail("E6011","cannot allocate coverage bitmap");
}
void vela_coverage_hit(int64_t id) {
    if (coverage_fd<0 || id<0 || id>=coverage_count)return;
    pthread_mutex_lock(&coverage_lock);
    if (!coverage_seen[id]) {
        coverage_seen[id]=1;
        char text[32];
        int n=snprintf(text,sizeof text,"%lld\n",(long long)id);
        ssize_t wrote;
        do {
            wrote=write(coverage_fd,text,(size_t)n);
        }
        while (wrote<0 && errno==EINTR);
        if (wrote!=n)cap_fail("E6011","cannot write coverage hit report");
    }
    pthread_mutex_unlock(&coverage_lock);
}
