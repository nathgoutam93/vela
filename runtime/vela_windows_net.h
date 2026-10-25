// Winsock adapters used by the shared network/fake implementation.
typedef intptr_t sys_fd;
static int win_socket_error(void) {
    int e=WSAGetLastError();
    errno=e==WSAEWOULDBLOCK?EAGAIN:e==WSAEINPROGRESS?EINPROGRESS:e==WSAEINTR?EINTR:
          e==WSAECONNREFUSED?ECONNREFUSED:e==WSAETIMEDOUT?ETIMEDOUT:e==WSAEBADF?EBADF:EIO;
    return -1;
}
static BOOL CALLBACK win_wsa_init(PINIT_ONCE once,void *arg,void **context) {
    (void)once;(void)arg;(void)context;WSADATA data;return WSAStartup(MAKEWORD(2,2),&data)==0;
}
static int win_getaddrinfo(const char *node,const char *service,const struct addrinfo *hints,struct addrinfo **out) {
    static INIT_ONCE once=INIT_ONCE_STATIC_INIT;
    if(!InitOnceExecuteOnce(&once,win_wsa_init,NULL,NULL))return EAI_FAIL;
    return getaddrinfo(node,service,hints,out);
}
static sys_fd win_socket(int family,int type,int protocol) {
    static INIT_ONCE once=INIT_ONCE_STATIC_INIT;
    if(!InitOnceExecuteOnce(&once,win_wsa_init,NULL,NULL)){errno=EIO;return -1;}
    SOCKET s=WSASocketW(family,type,protocol,NULL,0,WSA_FLAG_OVERLAPPED|WSA_FLAG_NO_HANDLE_INHERIT);
    return s==INVALID_SOCKET?win_socket_error():(sys_fd)s;
}
static int win_connect(sys_fd s,const struct sockaddr *a,socklen_t n) {
    int r=connect((SOCKET)s,a,n);if(r){int e=WSAGetLastError();if(e==WSAEWOULDBLOCK){errno=EINPROGRESS;return -1;}return win_socket_error();}return r;
}
static int win_bind(sys_fd s,const struct sockaddr *a,socklen_t n) {return bind((SOCKET)s,a,n)?win_socket_error():0;}
static int win_listen(sys_fd s,int n) {return listen((SOCKET)s,n)?win_socket_error():0;}
static sys_fd win_accept(sys_fd s,struct sockaddr *a,socklen_t *n) { SOCKET r=accept((SOCKET)s,a,n);return r==INVALID_SOCKET?win_socket_error():(sys_fd)r; }
static int win_getsockopt(sys_fd s,int level,int option,void *p,socklen_t *n) {return getsockopt((SOCKET)s,level,option,p,n)?win_socket_error():0;}
static int win_setsockopt(sys_fd s,int level,int option,const void *p,socklen_t n) {return setsockopt((SOCKET)s,level,option,p,n)?win_socket_error():0;}
static ssize_t win_recv(sys_fd s,void *p,size_t n,int flags) {int r=recv((SOCKET)s,p,n>INT_MAX?INT_MAX:(int)n,flags);return r<0?win_socket_error():r;}
static ssize_t win_send(sys_fd s,const void *p,size_t n) {int r=send((SOCKET)s,p,n>INT_MAX?INT_MAX:(int)n,0);return r<0?win_socket_error():r;}
static ssize_t win_sendto(sys_fd s,const void *p,size_t n,int flags,const struct sockaddr *a,socklen_t len) {int r=sendto((SOCKET)s,p,(int)n,flags,a,len);return r<0?win_socket_error():r;}
static ssize_t win_recvfrom(sys_fd s,void *p,size_t n,int flags,struct sockaddr *a,socklen_t *len) {int r=recvfrom((SOCKET)s,p,(int)n,flags,a,len);return r<0?win_socket_error():r;}
#define F_SETFD 1
#define FD_CLOEXEC 1
#define F_SETFL 2
#define O_NONBLOCK 1
#define F_DUPFD_CLOEXEC 3
static sys_fd win_fcntl(sys_fd fd,int command,int value) {
    (void)value;
    if(command==F_SETFD){if(SetHandleInformation((HANDLE)fd,HANDLE_FLAG_INHERIT,0))return 0;win_errno(GetLastError());return -1;}
    if(command==F_SETFL){u_long mode=1;return ioctlsocket((SOCKET)fd,FIONBIO,&mode)?win_socket_error():0;}
    WSAPROTOCOL_INFOW info;
    if(WSADuplicateSocketW((SOCKET)fd,GetCurrentProcessId(),&info))return win_socket_error();
    SOCKET s=WSASocketW(FROM_PROTOCOL_INFO,FROM_PROTOCOL_INFO,FROM_PROTOCOL_INFO,&info,0,WSA_FLAG_OVERLAPPED|WSA_FLAG_NO_HANDLE_INHERIT);
    return s==INVALID_SOCKET?win_socket_error():(sys_fd)s;
}
static int win_poll(WSAPOLLFD *p,unsigned long n,int timeout) {int r=WSAPoll(p,n,timeout);return r<0?win_socket_error():r;}
#define getaddrinfo win_getaddrinfo
#define socket win_socket
#define connect win_connect
#define bind win_bind
#define listen win_listen
#define accept win_accept
#define getsockopt win_getsockopt
#define setsockopt win_setsockopt
#define recv win_recv
#define sendto win_sendto
#define recvfrom win_recvfrom
#define fcntl win_fcntl
#define poll win_poll
#define sys_close(fd) closesocket((SOCKET)(fd))
