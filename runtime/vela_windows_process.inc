// CreateProcess receives quoted UTF-16 arguments and an explicit inherited-handle
// list. The bounded process API drains stdout/stderr while a writer feeds stdin.
static wchar_t *win_command(vela_array *args,vela_str *error) {
    if(!args->len || !sys_word(args,0).len){sys_error(error,"process needs a program");return NULL;}
    vela_array *text=vela_array_new(&vela_type_byte,0);
    for(int64_t i=0;i<args->len;i++) {
        char *arg=c_path(sys_word(args,i));
        if(!arg){vela_array_release(text);sys_error(error,"argument contains a zero byte");return NULL;}
        if(i)vela_builder_add(text,VELA_STR(" ",1));
        vela_builder_add(text,VELA_STR("\"",1));
        size_t slashes=0;
        for(const char *p=arg;;p++) {
            if(*p=='\\'){slashes++;continue;}
            size_t copies=slashes;
            if(*p=='"' || !*p)copies*=2;
            for(size_t j=0;j<copies;j++)vela_builder_add(text,VELA_STR("\\",1));
            slashes=0;
            if(!*p)break;
            if(*p=='"')vela_builder_add(text,VELA_STR("\\",1));
            vela_builder_add(text,(vela_str){NULL,(const uint8_t*)p,1});
        }
        vela_builder_add(text,VELA_STR("\"",1));free(arg);
    }
    vela_str command=vela_builder_build(text);char *utf8=c_path(command);
    wchar_t *wide=win_wide(utf8);free(utf8);vela_str_release(command);
    if(!wide)sys_errno(error);return wide;
}
static bool win_spawn(vela_array *args,HANDLE handles[3],bool suspended,PROCESS_INFORMATION *process,vela_str *error) {
    wchar_t *command=win_command(args,error);if(!command)return false;
    STARTUPINFOEXW startup;memset(&startup,0,sizeof startup);startup.StartupInfo.cb=sizeof startup;
    startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput=handles[0];startup.StartupInfo.hStdOutput=handles[1];startup.StartupInfo.hStdError=handles[2];
    SIZE_T size=0;InitializeProcThreadAttributeList(NULL,1,0,&size);
    startup.lpAttributeList=vela_alloc(size);
    bool initialized=InitializeProcThreadAttributeList(startup.lpAttributeList,1,0,&size)!=0;
    bool ok=initialized && UpdateProcThreadAttribute(startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles,3*sizeof(HANDLE),NULL,NULL);
    char *first=c_path(sys_word(args,0));
    bool explicit_path=first && (strchr(first,'/') || strchr(first,'\\') || strchr(first,':'));
    wchar_t *application=explicit_path?win_wide(first):NULL;free(first);
    if(explicit_path && !application)ok=false;
    if(ok)ok=CreateProcessW(application,command,NULL,NULL,TRUE,EXTENDED_STARTUPINFO_PRESENT|(suspended?CREATE_SUSPENDED:0),NULL,NULL,&startup.StartupInfo,process)!=0;
    DWORD saved=GetLastError();if(initialized)DeleteProcThreadAttributeList(startup.lpAttributeList);
    free(startup.lpAttributeList);free(command);free(application);
    if(!ok){win_errno(saved);return sys_errno(error);}return true;
}
typedef struct {HANDLE pipe;vela_str input;} win_writer;
static DWORD WINAPI win_write_input(void *value) {
    win_writer *writer=value;int64_t pos=0;
    while(pos<writer->input.len) {
        DWORD n=0;DWORD size=writer->input.len-pos>65536?65536:(DWORD)(writer->input.len-pos);
        if(!WriteFile(writer->pipe,writer->input.data+pos,size,&n,NULL)||!n)break;pos+=n;
    }
    CloseHandle(writer->pipe);return 0;
}
static bool win_process(vela_array *args,vela_str input,int64_t limit,int64_t timeout,vela_array **out,vela_str *error) {
    SECURITY_ATTRIBUTES security={sizeof security,NULL,TRUE};
    HANDLE reads[3]={NULL,NULL,NULL},writes[3]={NULL,NULL,NULL};
    PROCESS_INFORMATION process;memset(&process,0,sizeof process);
    HANDLE writer=NULL,job=NULL;bool ok=true;
    vela_array *data[2]={vela_array_new(&vela_type_byte,0),vela_array_new(&vela_type_byte,0)};
    for(int i=0;i<3;i++) {
        if(!CreatePipe(&reads[i],&writes[i],&security,0) || !SetHandleInformation(i==0?writes[i]:reads[i],HANDLE_FLAG_INHERIT,0)) {win_errno(GetLastError());ok=sys_errno(error);break;}
    }
    if(ok){job=CreateJobObjectW(NULL,NULL);if(!job){win_errno(GetLastError());ok=sys_errno(error);}}
    if(ok){HANDLE handles[3]={reads[0],writes[1],writes[2]};fflush(stdout);fflush(stderr);ok=win_spawn(args,handles,true,&process,error);}
    if(ok && !AssignProcessToJobObject(job,process.hProcess)){win_errno(GetLastError());ok=sys_errno(error);}
    if(process.hProcess) {CloseHandle(reads[0]);reads[0]=NULL;for(int i=1;i<3;i++){CloseHandle(writes[i]);writes[i]=NULL;}}
    win_writer state={writes[0],input};
    if(ok){writer=CreateThread(NULL,0,win_write_input,&state,0,NULL);if(!writer){win_errno(GetLastError());ok=sys_errno(error);}else writes[0]=NULL;}
    if(ok && ResumeThread(process.hThread)==(DWORD)-1){win_errno(GetLastError());ok=sys_errno(error);}
    ULONGLONG started=GetTickCount64();int64_t total=0;DWORD status=0;
    while(ok) {
        bool open=false,progress=false;
        for(int i=1;i<3 && ok;i++)if(reads[i]) {
            DWORD available=0;
            if(!PeekNamedPipe(reads[i],NULL,0,NULL,&available,NULL)) {
                DWORD code=GetLastError();if(code==ERROR_BROKEN_PIPE){CloseHandle(reads[i]);reads[i]=NULL;continue;}
                win_errno(code);ok=sys_errno(error);break;
            }
            open=true;
            if(available){char buffer[8192];DWORD n=0,size=available>sizeof buffer?sizeof buffer:available;
                if(!ReadFile(reads[i],buffer,size,&n,NULL)){win_errno(GetLastError());ok=sys_errno(error);break;}
                if((uint64_t)n>(uint64_t)(limit-total)){ok=sys_error(error,"process output limit exceeded");break;}
                total+=n;vela_builder_add(data[i-1],(vela_str){NULL,(const uint8_t*)buffer,n});progress=true;
            }
        }
        if(!ok)break;
        DWORD waited=WaitForSingleObject(process.hProcess,0);
        if(waited==WAIT_FAILED){win_errno(GetLastError());ok=sys_errno(error);break;}
        if(waited==WAIT_OBJECT_0 && !open){GetExitCodeProcess(process.hProcess,&status);break;}
        if(GetTickCount64()-started>=(ULONGLONG)timeout){ok=sys_error(error,"process timeout");break;}
        if(!progress)Sleep(1);
    }
    if(!ok && process.hProcess){if(job)TerminateJobObject(job,1);TerminateProcess(process.hProcess,1);}
    // Errors/timeouts terminate the group; successful descendants retain the
    // same lifetime semantics as the POSIX process API.
    if(job)CloseHandle(job);
    if(writer){CancelSynchronousIo(writer);WaitForSingleObject(writer,INFINITE);CloseHandle(writer);}
    if(process.hProcess){WaitForSingleObject(process.hProcess,INFINITE);CloseHandle(process.hProcess);CloseHandle(process.hThread);}
    for(int i=0;i<3;i++){if(reads[i])CloseHandle(reads[i]);if(writes[i])CloseHandle(writes[i]);}
    if(ok){*out=vela_array_new(&vela_type_str,3);vela_str values[3]={vela_from_int(status),vela_builder_build(data[0]),vela_builder_build(data[1])};
        data[0]=data[1]=NULL;for(int i=0;i<3;i++){sys_push(*out,values[i]);vela_str_release(values[i]);}}
    if(data[0])vela_array_release(data[0]);if(data[1])vela_array_release(data[1]);return ok;
}
static bool win_run_program(vela_array *args,int64_t *code,vela_str *error,vela_str *captured) {
    HANDLE handles[3]={NULL,NULL,NULL};DWORD ids[3]={STD_INPUT_HANDLE,STD_OUTPUT_HANDLE,STD_ERROR_HANDLE};bool ok=true;
    for(int i=0;i<3;i++) {
        HANDLE source=GetStdHandle(ids[i]);
        if(!source||source==INVALID_HANDLE_VALUE){SECURITY_ATTRIBUTES sa={sizeof sa,NULL,TRUE};handles[i]=CreateFileW(L"NUL",GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,NULL);}
        else if(!DuplicateHandle(GetCurrentProcess(),source,GetCurrentProcess(),&handles[i],0,TRUE,DUPLICATE_SAME_ACCESS))handles[i]=INVALID_HANDLE_VALUE;
        if(handles[i]==INVALID_HANDLE_VALUE){handles[i]=NULL;win_errno(GetLastError());ok=sys_errno(error);break;}
    }
    HANDLE read_output=NULL;
    if(ok && captured) {
        SECURITY_ATTRIBUTES sa={sizeof sa,NULL,TRUE};HANDLE output=NULL;
        if(!CreatePipe(&read_output,&output,&sa,0) || !SetHandleInformation(read_output,HANDLE_FLAG_INHERIT,0)) {
            if(output)CloseHandle(output);win_errno(GetLastError());ok=sys_errno(error);
        } else {CloseHandle(handles[1]);handles[1]=output;}
    }
    PROCESS_INFORMATION process;memset(&process,0,sizeof process);fflush(stdout);fflush(stderr);
    if(ok)ok=win_spawn(args,handles,false,&process,error);
    for(int i=0;i<3;i++)if(handles[i])CloseHandle(handles[i]);
    if(ok && captured) {
        vela_array *text=vela_array_new(&vela_type_byte,0);
        for(;;){char buffer[8192];DWORD n=0;
            if(!ReadFile(read_output,buffer,sizeof buffer,&n,NULL)) {
                DWORD reason=GetLastError();if(reason!=ERROR_BROKEN_PIPE){win_errno(reason);ok=sys_errno(error);TerminateProcess(process.hProcess,1);}break;
            }
            if(!n)break;vela_builder_add(text,(vela_str){NULL,(const uint8_t*)buffer,n});
        }
        if(ok)*captured=vela_builder_build(text);else vela_array_release(text);
    }
    if(read_output)CloseHandle(read_output);
    if(process.hProcess){DWORD status=0;WaitForSingleObject(process.hProcess,INFINITE);GetExitCodeProcess(process.hProcess,&status);*code=status;CloseHandle(process.hProcess);CloseHandle(process.hThread);}return ok;
}
