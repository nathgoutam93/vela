// Standalone Windows/WASI programs run within their host's authority. Restricted
// launch is rejected until an OS implementation can enforce it before C code.
bool vela_cap_check(const char *effect, vela_str path, vela_str *error) {
    (void)effect; (void)path; (void)error; return true;
}
void vela_cap_require(const char *effect) { (void)effect; }
bool vela_cap_process(vela_str *error) { (void)error; return true; }
void vela_policy_init(int argc, char **argv) { (void)argc; (void)argv; }
bool vela_sys_canonical(vela_str path, vela_str *out, vela_str *error) {
    if (files_faked) { *out=path; vela_str_retain(path); return true; }
    char *p=c_path(path);
    if (!p) return sys_error(error,"path contains a zero byte");
#if defined(__wasi__)
    free(p); return sys_error(error,"canonical paths are unsupported on WASI preview 1");
#else
    wchar_t *wide=win_wide(p);free(p);
    if(!wide)return sys_errno(error);
    char *resolved=win_resolved_path(wide);free(wide);
    if(!resolved)return sys_errno(error);
    *out=str_from(resolved,strlen(resolved)); free(resolved); return true;
#endif
}
bool vela_sys_sandbox_run(vela_array *command, vela_array *allow, vela_array *deny, int64_t *out, vela_str *error) {
#if defined(_WIN32)
    for(int64_t i=0;i<allow->len;i++)if(sys_word(allow,i).len>3 && !memcmp(sys_word(allow,i).data,"fs:",3))return sys_error(error,"OS capability enforcement is unsupported on this platform [E6011]");
    for(int64_t i=0;i<deny->len;i++)if(!sys_is(sys_word(deny,i),"unsafe"))return sys_error(error,"OS capability enforcement is unsupported on this platform [E6011]");
    return run_program(command,out,error,NULL);
#else
    (void)command; (void)allow; (void)deny; (void)out;
    return sys_error(error,"OS capability enforcement is unsupported on this platform [E6011]");
#endif
}
static pthread_mutex_t coverage_lock=PTHREAD_MUTEX_INITIALIZER;
static uint8_t *coverage_seen=NULL;
static int64_t coverage_count=0;
static FILE *coverage_file=NULL;
void vela_coverage_begin(int argc,char **argv,int64_t count) {
#if defined(_WIN32)
    argc=saved_argc;argv=saved_argv;
#endif
    if(argc<3)return;
    coverage_file=fopen(argv[2],"ab");
    if(!coverage_file)vela_panic("coverage","cannot open coverage hit report");
    coverage_count=count;coverage_seen=calloc((size_t)count+1,1);
    if(!coverage_seen)vela_panic("coverage","cannot allocate coverage bitmap");
}
void vela_coverage_hit(int64_t id) {
    if(!coverage_file || id<0 || id>=coverage_count)return;
    pthread_mutex_lock(&coverage_lock);
    if(!coverage_seen[id]) {
        coverage_seen[id]=1;
        if(fprintf(coverage_file,"%lld\n",(long long)id)<0 || fflush(coverage_file))vela_panic("coverage","cannot write coverage hit report");
    }
    pthread_mutex_unlock(&coverage_lock);
}
