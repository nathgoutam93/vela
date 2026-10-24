// M23 POSIX implementation; included by vela_rt.c and included in its cache key.
#include <sys/socket.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <poll.h>
#include <time.h>
#include <signal.h>
#include <spawn.h>
#include <dirent.h>
#include <sys/stat.h>
extern char **environ;
static bool sys_error(vela_str *e, const char *s) {
    *e = str_from(s, strlen(s));
    return false;
}
static bool sys_errno(vela_str *e) {
    return sys_error(e, strerror(errno));
}
static int64_t sys_now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) vela_panic("systems I/O", "monotonic clock unavailable");
    return (int64_t)ts.tv_sec*1000+ts.tv_nsec/1000000;
}
static bool sys_timeout(int64_t n, vela_str *e) {
    return (n>=0 && n<=86400000) || sys_error(e,"timeout must be between 0 and 86400000 milliseconds");
}
static bool sys_size(int64_t n, vela_str *e) {
    return (n>0 && n<=67108864) || sys_error(e,"size must be between 1 and 67108864 bytes");
}
static bool sys_port(int64_t n, bool zero, vela_str *e) {
    return (n>=(zero?0:1) && n<=65535) || sys_error(e,"invalid port");
}
static vela_str sys_word(vela_array *a, int64_t i) {
    return ((vela_str *)a->data)[i];
}
static bool sys_eq(vela_str a, vela_str b) {
    return a.len==b.len && (!a.len || memcmp(a.data,b.data,(size_t)a.len)==0);
}
static bool sys_is(vela_str a, const char *s) {
    return a.len==(int64_t)strlen(s) && !memcmp(a.data,s,(size_t)a.len);
}
static void sys_push(vela_array *a, vela_str s) {
    vela_str_retain(s);
    vela_array_push(a,&s);
}
static bool sys_wait(int fd, short events, int64_t deadline, vela_str *e) {
    for (; ; ) {
        int64_t left=deadline-sys_now();
        if (left<0) left=0;
        struct pollfd p= {
            fd,events,0
        };
        int r=poll(&p,1,(int)left);
        if (r>0) {
            if (p.revents&POLLNVAL) return sys_error(e,"closed descriptor");
            return true;
        }
        if (r==0) return sys_error(e,"I/O timeout");
        if (errno!=EINTR) return sys_errno(e);
    }
}
// Block SIGPIPE in this thread only; consume only the signal this write generated.
static ssize_t sys_write_fd(int fd,const void *p,size_t n) {
    sigset_t set,old,pending;
    sigemptyset(&set);
    sigaddset(&set,SIGPIPE);
    pthread_sigmask(SIG_BLOCK,&set,&old);
    sigpending(&pending);
    ssize_t r=write(fd,p,n);
    int saved=errno;
    if (r<0 && saved==EPIPE && !sigismember(&pending,SIGPIPE)) {
        sigset_t after;
        sigpending(&after);
        if (sigismember(&after,SIGPIPE)) {
            int sig;
            sigwait(&set,&sig);
        }
    }
    pthread_sigmask(SIG_SETMASK,&old,NULL);
    errno=saved;
    return r;
}
// Fakes are protected by fake_lock; a scope owns one reference, each socket another.
typedef struct sys_fake {
    int64_t refs;
    bool active;
    vela_array *rows;
    int64_t *used,*written;
}
sys_fake;
static sys_fake *sys_net=NULL,*sys_processes=NULL;
static sys_fake *sys_fake_new(vela_array *rows) {
    sys_fake *f=vela_alloc(sizeof *f);
    f->refs=1;
    f->active=true;
    f->rows=rows;
    vela_array_share(rows);
    f->used=calloc((size_t)rows->len+1,sizeof(int64_t));
    f->written=calloc((size_t)rows->len+1,sizeof(int64_t));
    if (!f->used || !f->written) vela_panic("with fake","out of memory");
    return f;
}
static void sys_fake_drop(sys_fake *f) {
    if (f && --f->refs==0) {
        vela_array_release(f->rows);
        free(f->used);
        free(f->written);
        free(f);
    }
}
static vela_array *sys_row(sys_fake *f,int64_t i) {
    return ((vela_array **)f->rows->data)[i];
}
static void *sys_set_fake(vela_array *a,sys_fake **slot,bool net) {
    for (int64_t i=0; i<a->len; i++) {
        vela_array *r=((vela_array **)a->data)[i];
        if (r->len < (net?4:5)) vela_panic("with fake","malformed transcript row");
    }
    sys_fake *old=*slot;
    *slot=sys_fake_new(a);
    return old;
}
void *vela_fake_net(vela_array *a) {
    return sys_set_fake(a,&sys_net,true);
}
void *vela_fake_processes(vela_array *a) {
    return sys_set_fake(a,&sys_processes,false);
}
static void sys_restore_fake(void *old,sys_fake **slot,bool net) {
    sys_fake *f=*slot;
    bool valid=true;
    lock_fakes();
    for (int64_t i=0; i<f->rows->len; i++) {
        vela_array *r=sys_row(f,i);
        if (!f->used[i]) valid=false;
        if (net && (sys_is(sys_word(r,0),"connect") || sys_is(sys_word(r,0),"accept")) && (r->len<5 || f->written[i]!=sys_word(r,3).len)) valid=false;
    }
    f->active=false;
    *slot=old;
    sys_fake_drop(f);
    unlock_fakes();
    if (!valid) vela_panic("with fake", "unconsumed fake request or incomplete network write");
}
void vela_fake_net_restore(void *o) {
    sys_restore_fake(o,&sys_net,true);
}
void vela_fake_processes_restore(void *o) {
    sys_restore_fake(o,&sys_processes,false);
}
typedef struct {
    int64_t wall,mono;
}
sys_clock_state;
static sys_clock_state *sys_clock=NULL;
void *vela_fake_clock(vela_array *a) {
    if (a->len!=2 || ((int64_t*)a->data)[1]<0) vela_panic("with clock","expected [wall_ns, nonnegative_monotonic_ns]");
    sys_clock_state *old=sys_clock;
    sys_clock=vela_alloc(sizeof *sys_clock);
    sys_clock->wall=((int64_t*)a->data)[0];
    sys_clock->mono=((int64_t*)a->data)[1];
    vela_array_release(a);
    return old;
}
void vela_fake_clock_restore(void *old) {
    free(sys_clock);
    sys_clock=old;
}
static bool sys_clock_read(bool mono,int64_t *out,vela_str *e) {
    lock_fakes();
    if (sys_clock) {
        *out=mono?sys_clock->mono:sys_clock->wall;
        unlock_fakes();
        return true;
    }
    unlock_fakes();
    struct timespec t;
    if (clock_gettime(mono?CLOCK_MONOTONIC:CLOCK_REALTIME,&t)) return sys_errno(e);
    if (t.tv_sec>INT64_MAX/1000000000 || t.tv_sec<INT64_MIN/1000000000) return sys_error(e,"clock out of nanosecond range");
    int64_t secs=(int64_t)t.tv_sec*1000000000;
    if (__builtin_add_overflow(secs,(int64_t)t.tv_nsec,out)) return sys_error(e,"clock out of nanosecond range");
    return true;
}
bool vela_sys_wall_ns(int64_t *o,vela_str *e) {
    return sys_clock_read(false,o,e);
}
bool vela_sys_monotonic_ns(int64_t *o,vela_str *e) {
    return sys_clock_read(true,o,e);
}
bool vela_sys_sleep_ns(int64_t n,vela_unit *o,vela_str *e) {
    if (n<0) return sys_error(e,"negative sleep");
    *o=0;
    lock_fakes();
    if (sys_clock) {
        int64_t w,m;
        if (__builtin_add_overflow(sys_clock->wall,n,&w)||__builtin_add_overflow(sys_clock->mono,n,&m)) {
            unlock_fakes();
            return sys_error(e,"fake clock overflow");
        }
        sys_clock->wall=w;
        sys_clock->mono=m;
        unlock_fakes();
        return true;
    }
    unlock_fakes();
    struct timespec t= {
        n/1000000000,n%1000000000
    };
    while (nanosleep(&t,&t)) if (errno!=EINTR) return sys_errno(e);
    return true;
}
struct vela_io_handle {
    int64_t rc;
    pthread_mutex_t lock;
    int fd,kind,family;
    bool closed;
    int64_t timeout,port,row,pos;
    vela_str host;
    sys_fake *fake;
};
static vela_io_handle *sys_handle(int fd,int kind,int family,int64_t port,vela_str host,sys_fake *fake,int64_t row,int64_t timeout) {
    vela_io_handle *h=vela_alloc(sizeof *h);
    *h=(vela_io_handle) {
        .rc=1,.fd=fd,.kind=kind,.family=family,.port=port,.host=host,.fake=fake,.row=row,.timeout=timeout
    };
    vela_str_retain(host);
    pthread_mutex_init(&h->lock,NULL);
    if (fake) fake->refs++;
    return h;
}
void vela_handle_retain(vela_io_handle *h) {
    if (h) vela_rc_inc(&h->rc);
}
void vela_handle_share(vela_io_handle *h) {
    if (h && vela_rc_share(&h->rc)) vela_str_share(h->host);
}
void vela_handle_release(vela_io_handle *h) {
    if (h && vela_rc_dec(&h->rc)) {
        if (h->fd>=0) close(h->fd);
        lock_fakes();
        sys_fake_drop(h->fake);
        unlock_fakes();
        vela_str_release(h->host);
        pthread_mutex_destroy(&h->lock);
        free(h);
    }
}
static void sys_handle_retain_value(void *p) {
    vela_handle_retain(*(vela_io_handle**)p);
}
static void sys_handle_release_value(void *p) {
    vela_handle_release(*(vela_io_handle**)p);
}
static void sys_handle_share_value(void *p) {
    vela_handle_share(*(vela_io_handle**)p);
}
const vela_type vela_type_io_handle= {
    sizeof(vela_io_handle*),sys_handle_retain_value,sys_handle_release_value,NULL,NULL,sys_handle_share_value
};
// Called with handle lock held. All fake operations additionally hold fake_lock.
static bool sys_live(vela_io_handle *h,int kind,vela_str *e) {
    if (h->closed) return sys_error(e,"socket is closed");
    if (kind && h->kind!=kind) return sys_error(e,"wrong socket kind");
    if ((h->fake && (!h->fake->active || h->fake!=sys_net)) || (!h->fake && sys_net)) return sys_error(e,"socket does not belong to the active network scope");
    return true;
}
static int64_t sys_claim(sys_fake *f,const char *kind,vela_str host,int64_t port) {
    vela_str p=vela_from_int(port);
    int64_t found=-1;
    for (int64_t i=0; i<f->rows->len; i++) {
        vela_array *r=sys_row(f,i);
        if (!f->used[i] && r->len>=4 && sys_is(sys_word(r,0),kind) && sys_eq(sys_word(r,1),host) && sys_eq(sys_word(r,2),p)) {
            f->used[i]=1;
            found=i;
            break;
        }
    }
    vela_str_release(p);
    return found;
}
static int sys_socket(int family,int type) {
    pthread_mutex_lock(&fork_lock);
    int fd=socket(family,type,0);
    if (fd>=0 && (fcntl(fd,F_SETFD,FD_CLOEXEC)<0 || fcntl(fd,F_SETFL,O_NONBLOCK)<0)) {
        int e=errno;
        close(fd);
        fd=-1;
        errno=e;
    }
    pthread_mutex_unlock(&fork_lock);
    return fd;
}
static int64_t sys_bound_port(int fd) {
    struct sockaddr_storage s;
    socklen_t n=sizeof s;
    if (getsockname(fd,(struct sockaddr*)&s,&n)) return -1;
    return s.ss_family==AF_INET?ntohs(((struct sockaddr_in*)&s)->sin_port):ntohs(((struct sockaddr_in6*)&s)->sin6_port);
}
static bool sys_open(vela_str host,int64_t port,int64_t timeout,int kind,vela_io_handle **out,vela_str *e) {
    if (!sys_timeout(timeout,e)||!sys_port(port,kind!=1,e)) return false;
    char *name=c_path(host);
    if (!name) return sys_error(e,"host contains a zero byte");
    if (!*name) {
        free(name);
        return sys_error(e,"empty host");
    }
    lock_fakes();
    if (sys_net) {
        free(name);
        int64_t row=-1;
        if (kind==1) {
            row=sys_claim(sys_net,"error",host,port);
            if (row>=0) {
                *e=sys_word(sys_row(sys_net,row),3);
                vela_str_retain(*e);
                unlock_fakes();
                return false;
            }
            row=sys_claim(sys_net,"connect",host,port);
            if (row<0 || sys_row(sys_net,row)->len!=5) {
                unlock_fakes();
                return sys_error(e,"unexpected fake connection");
            }
        }
        *out=sys_handle(-1,kind,AF_INET,port?port:40000,host,sys_net,row,timeout);
        unlock_fakes();
        return true;
    }
    unlock_fakes();
    char service[16];
    snprintf(service,sizeof service,"%lld",(long long)port);
    struct addrinfo hints= {
        0
    },*list=NULL;
    hints.ai_family=AF_UNSPEC;
    hints.ai_socktype=kind==3?SOCK_DGRAM:SOCK_STREAM;
    int code=getaddrinfo(name,service,&hints,&list);
    free(name);
    if (code) return sys_error(e,gai_strerror(code));
    int fd=-1,family=0,saved=ECONNREFUSED;
    int64_t deadline=sys_now()+timeout;
    for (struct addrinfo *a=list; a; a=a->ai_next) {
        fd=sys_socket(a->ai_family,a->ai_socktype);
        if (fd<0) {
            saved=errno;
            continue;
        }
        family=a->ai_family;
        if (kind==1) {
            if (connect(fd,a->ai_addr,a->ai_addrlen)==0) break;
            if (errno==EINPROGRESS) {
                vela_str why=VELA_STR("",0);
                if (sys_wait(fd,POLLOUT,deadline,&why)) {
                    int err=0;
                    socklen_t n=sizeof err;
                    if (!getsockopt(fd,SOL_SOCKET,SO_ERROR,&err,&n) && !err) break;
                    saved=err?err:errno;
                } else {
                    vela_str_release(why);
                    saved=ETIMEDOUT;
                }
            } else saved=errno;
        } else {
            int yes=1;
            setsockopt(fd,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof yes);
            if (bind(fd,a->ai_addr,a->ai_addrlen)==0 && (kind==3 || listen(fd,128)==0)) break;
            saved=errno;
        }
        close(fd);
        fd=-1;
    }
    freeaddrinfo(list);
    if (fd<0) {
        errno=saved;
        return sys_errno(e);
    }
    *out=sys_handle(fd,kind,family,sys_bound_port(fd),host,NULL,-1,timeout);
    return true;
}
bool vela_sys_tcp_connect(vela_str h,int64_t p,int64_t t,vela_io_handle **o,vela_str *e) {
    return sys_open(h,p,t,1,o,e);
}
bool vela_sys_tcp_listen(vela_str h,int64_t p,int64_t t,vela_io_handle **o,vela_str *e) {
    return sys_open(h,p,t,2,o,e);
}
bool vela_sys_udp_bind(vela_str h,int64_t p,vela_io_handle **o,vela_str *e) {
    return sys_open(h,p,5000,3,o,e);
}
// Pin the open file description for an operation, then release the handle lock.
// This permits full duplex I/O and prevents close/reuse races. Closing an alias
// rejects subsequent operations; an already-running operation finishes/times out.
static int sys_borrow_fd(vela_io_handle *h) {
    pthread_mutex_lock(&fork_lock);
    int fd=fcntl(h->fd,F_DUPFD_CLOEXEC,3);
    pthread_mutex_unlock(&fork_lock);
    return fd;
}
bool vela_sys_accept(vela_io_handle *h,vela_io_handle **o,vela_str *e) {
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,2,e);
    if (ok && h->fake) {
        int64_t i=sys_claim(h->fake,"accept",h->host,h->port);
        if (i<0 || sys_row(h->fake,i)->len!=5) ok=sys_error(e,"unexpected fake accept");
        else *o=sys_handle(-1,1,AF_INET,h->port,h->host,h->fake,i,h->timeout);
        unlock_fakes();
        pthread_mutex_unlock(&h->lock);
        return ok;
    }
    unlock_fakes();
    int fd=-1;
    int64_t timeout=h->timeout;
    if (ok) {
        fd=sys_borrow_fd(h);
        if (fd<0)ok=sys_errno(e);
    }
    pthread_mutex_unlock(&h->lock);
    if (ok) {
        int64_t deadline=sys_now()+timeout;
        int accepted=-1;
        for (; ; ) {
            if (!sys_wait(fd,POLLIN,deadline,e)) {
                ok=false;
                break;
            }
            pthread_mutex_lock(&fork_lock);
            accepted=accept(fd,NULL,NULL);
            if (accepted>=0 && (fcntl(accepted,F_SETFD,FD_CLOEXEC)<0 || fcntl(accepted,F_SETFL,O_NONBLOCK)<0)) {
                int saved=errno;
                close(accepted);
                accepted=-1;
                errno=saved;
            }
            pthread_mutex_unlock(&fork_lock);
            if (accepted>=0) break;
            if (errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK) {
                ok=sys_errno(e);
                break;
            }
        }
        if (ok) *o=sys_handle(accepted,1,h->family,sys_bound_port(accepted),h->host,NULL,-1,timeout);
    }
    if (fd>=0)close(fd);
    return ok;
}
bool vela_sys_net_read(vela_io_handle *h,int64_t max,vela_str *o,vela_str *e) {
    if (!sys_size(max,e)) return false;
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,1,e);
    if (ok && h->fake) {
        vela_str data=sys_word(sys_row(h->fake,h->row),4);
        int64_t n=data.len-h->pos;
        if (n>max)n=max;
        *o=str_from((const char*)data.data+h->pos,(size_t)n);
        h->pos+=n;
        unlock_fakes();
        pthread_mutex_unlock(&h->lock);
        return true;
    }
    unlock_fakes();
    int fd=-1;
    int64_t timeout=h->timeout;
    if (ok) {
        fd=sys_borrow_fd(h);
        if (fd<0)ok=sys_errno(e);
    }
    pthread_mutex_unlock(&h->lock);
    if (ok) {
        char *buf=vela_alloc((size_t)max);
        int64_t deadline=sys_now()+timeout;
        for (; ; ) {
            if (!sys_wait(fd,POLLIN,deadline,e)) {
                ok=false;
                break;
            }
            ssize_t n=recv(fd,buf,(size_t)max,0);
            if (n>=0) {
                *o=str_from(buf,(size_t)n);
                break;
            }
            if (errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK) {
                ok=sys_errno(e);
                break;
            }
        }
        free(buf);
    }
    if (fd>=0)close(fd);
    return ok;
}
bool vela_sys_net_write(vela_io_handle *h,vela_str data,int64_t *o,vela_str *e) {
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,1,e);
    if (ok && h->fake) {
        vela_str expected=sys_word(sys_row(h->fake,h->row),3);
        int64_t pos=h->fake->written[h->row];
        if (data.len>expected.len-pos || memcmp(expected.data+pos,data.data,(size_t)data.len)) ok=sys_error(e,"unexpected fake write");
        else {
            h->fake->written[h->row]+=data.len;
            *o=data.len;
        }
        unlock_fakes();
        pthread_mutex_unlock(&h->lock);
        return ok;
    }
    unlock_fakes();
    int fd=-1;
    int64_t timeout=h->timeout;
    if (ok) {
        fd=sys_borrow_fd(h);
        if (fd<0)ok=sys_errno(e);
    }
    pthread_mutex_unlock(&h->lock);
    if (ok) {
        int64_t pos=0,deadline=sys_now()+timeout;
        while (pos<data.len) {
            if (!sys_wait(fd,POLLOUT,deadline,e)) {
                ok=false;
                break;
            }
            ssize_t n=sys_write_fd(fd,data.data+pos,(size_t)(data.len-pos));
            if (n>0) pos+=n;
            else if (n==0 || (errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK)) {
                ok=sys_errno(e);
                break;
            }
        }
        if (ok)*o=pos;
    }
    if (fd>=0)close(fd);
    return ok;
}
bool vela_sys_net_close(vela_io_handle *h,vela_unit *o,vela_str *e) {
    pthread_mutex_lock(&h->lock);lock_fakes();
    bool ok=true;
    if ((h->fake && (!h->fake->active || h->fake!=sys_net)) || (!h->fake && sys_net)) {
        ok=sys_error(e,"socket does not belong to the active network scope");
    } else if (!h->closed) {
        h->closed=true;
        if (h->fd>=0) {close(h->fd);h->fd=-1;}
    }
    unlock_fakes();pthread_mutex_unlock(&h->lock);*o=0;return ok;
}
bool vela_sys_net_port(vela_io_handle *h,int64_t *o,vela_str *e) {
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,0,e);
    if (ok)*o=h->port;
    unlock_fakes();
    pthread_mutex_unlock(&h->lock);
    return ok;
}
bool vela_sys_net_timeout(vela_io_handle *h,int64_t n,vela_unit *o,vela_str *e) {
    if (!sys_timeout(n,e))return false;
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,0,e);
    if (ok)h->timeout=n;
    unlock_fakes();
    pthread_mutex_unlock(&h->lock);
    *o=0;
    return ok;
}
bool vela_sys_udp_send(vela_io_handle *h,vela_str host,int64_t port,vela_str data,int64_t *o,vela_str *e) {
    if (!sys_port(port,false,e))return false;
    if (data.len>65507)return sys_error(e,"UDP payload exceeds 65507 bytes");
    char *name=c_path(host);
    if (!name || !*name) {
        free(name);
        return sys_error(e,"invalid UDP host");
    }
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,3,e);
    if (ok && h->fake) {
        int64_t i=sys_claim(h->fake,"udp-out",host,port);
        if (i<0 || !sys_eq(sys_word(sys_row(h->fake,i),3),data))ok=sys_error(e,"unexpected fake datagram");
        else *o=data.len;
        free(name);
        unlock_fakes();
        pthread_mutex_unlock(&h->lock);
        return ok;
    }
    unlock_fakes();
    int fd=-1;
    int64_t timeout=h->timeout;
    if (ok) {
        fd=sys_borrow_fd(h);
        if (fd<0)ok=sys_errno(e);
    }
    pthread_mutex_unlock(&h->lock);
    if (ok) {
        struct addrinfo hints= {
            0
        },*a=NULL;
        hints.ai_family=h->family;
        hints.ai_socktype=SOCK_DGRAM;
        char p[16];
        snprintf(p,sizeof p,"%lld",(long long)port);
        int code=getaddrinfo(name,p,&hints,&a);
        if (code)ok=sys_error(e,gai_strerror(code));
        else {
            int64_t deadline=sys_now()+timeout;
            for (; ; ) {
                if (!sys_wait(fd,POLLOUT,deadline,e)) {
                    ok=false;
                    break;
                }
                ssize_t n=sendto(fd,data.data,(size_t)data.len,0,a->ai_addr,a->ai_addrlen);
                if (n>=0) {
                    *o=n;
                    break;
                }
                if (errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK) {
                    ok=sys_errno(e);
                    break;
                }
            }
            freeaddrinfo(a);
        }
    }
    free(name);
    if (fd>=0)close(fd);
    return ok;
}
bool vela_sys_udp_receive(vela_io_handle *h,int64_t max,vela_array **o,vela_str *e) {
    if (!sys_size(max,e))return false;
    pthread_mutex_lock(&h->lock);
    lock_fakes();
    bool ok=sys_live(h,3,e);
    if (ok && h->fake) {
        int64_t i=sys_claim(h->fake,"udp-in",h->host,h->port);
        vela_array *r=i<0?NULL:sys_row(h->fake,i);
        if (!r || r->len!=6)ok=sys_error(e,"unexpected fake receive");
        else if (sys_word(r,3).len>max)ok=sys_error(e,"datagram exceeds receive limit");
        else {
            *o=vela_array_new(&vela_type_str,3);
            for (int j=3; j<6; j++)sys_push(*o,sys_word(r,j));
        }
        unlock_fakes();
        pthread_mutex_unlock(&h->lock);
        return ok;
    }
    unlock_fakes();
    int fd=-1;
    int64_t timeout=h->timeout;
    if (ok) {
        fd=sys_borrow_fd(h);
        if (fd<0)ok=sys_errno(e);
    }
    pthread_mutex_unlock(&h->lock);
    if (ok) {
        char *buf=vela_alloc((size_t)max+1);
        int64_t deadline=sys_now()+timeout;
        for (; ; ) {
            if (!sys_wait(fd,POLLIN,deadline,e)) {
                ok=false;
                break;
            }
            struct sockaddr_storage peer;
            socklen_t plen=sizeof peer;
            ssize_t n=recvfrom(fd,buf,(size_t)max+1,0,(struct sockaddr*)&peer,&plen);
            if (n>=0) {
                if (n>max)ok=sys_error(e,"datagram exceeds receive limit");
                else {
                    char host[1025],port[32];
                    int code=getnameinfo((struct sockaddr*)&peer,plen,host,sizeof host,port,sizeof port,NI_NUMERICHOST|NI_NUMERICSERV);
                    if (code)ok=sys_error(e,gai_strerror(code));
                    else {
                        *o=vela_array_new(&vela_type_str,3);
                        vela_str vals[3]= {
                            str_from(buf,(size_t)n),str_from(host,strlen(host)),str_from(port,strlen(port))
                        };
                        for (int j=0; j<3; j++) {
                            sys_push(*o,vals[j]);
                            vela_str_release(vals[j]);
                        }
                    }
                }
                break;
            }
            if (errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK) {
                ok=sys_errno(e);
                break;
            }
        }
        free(buf);
    }
    if (fd>=0)close(fd);
    return ok;
}
// Communicate on all three pipes concurrently. Limits apply to combined output.
static bool sys_process_fake(vela_array *args,vela_str input,int64_t limit,vela_array **out,vela_str *e,bool *handled) {
    lock_fakes();
    sys_fake *f=sys_processes;
    *handled=f!=NULL;
    if (!f) {
        unlock_fakes();
        return false;
    }
    for (int64_t i=0; i<f->rows->len; i++) {
        vela_array *r=sys_row(f,i);
        if (f->used[i] || r->len!=args->len+5 || !sys_eq(sys_word(r,1),input))continue;
        bool match=true;
        for (int64_t j=0; j<args->len; j++)if (!sys_eq(sys_word(r,j+5),sys_word(args,j)))match=false;
        if (!match)continue;
        f->used[i]=1;
        if (sys_is(sys_word(r,0),"error")) {
            *e=sys_word(r,3);
            vela_str_retain(*e);
            unlock_fakes();
            return false;
        }
        if (!sys_is(sys_word(r,0),"ok")) {
            unlock_fakes();
            return sys_error(e,"invalid process fake");
        }
        if (sys_word(r,3).len>limit || sys_word(r,4).len>limit-sys_word(r,3).len) {
            unlock_fakes();
            return sys_error(e,"process output limit exceeded");
        }
        *out=vela_array_new(&vela_type_str,3);
        for (int j=2; j<5; j++)sys_push(*out,sys_word(r,j));
        unlock_fakes();
        return true;
    }
    unlock_fakes();
    return sys_error(e,"unexpected fake process");
}
static void sys_close_pipes(int p[3][2]) {
    for (int i=0; i<3; i++)for (int j=0; j<2; j++)if (p[i][j]>=0) {
        close(p[i][j]);
        p[i][j]=-1;
    }
}
bool vela_sys_process(vela_array *args,vela_str input,int64_t limit,int64_t timeout,vela_array **out,vela_str *e) {
    if (!sys_size(limit,e)||!sys_timeout(timeout,e))return false;
    if (args->len==0 || sys_word(args,0).len==0)return sys_error(e,"process needs a program");
    char **argv=vela_alloc(((size_t)args->len+1)*sizeof(char*));
    bool valid=true;
    int64_t copied=0;
    for (; copied<args->len; copied++) {
        argv[copied]=c_path(sys_word(args,copied));
        if (!argv[copied]) {
            valid=false;
            break;
        }
    }
    argv[copied]=NULL;
    if (!valid) {
        for (int64_t i=0; i<copied; i++)free(argv[i]);
        free(argv);
        return sys_error(e,"argument contains a zero byte");
    }
    bool handled=false;
    bool ok=sys_process_fake(args,input,limit,out,e,&handled);
    if (handled) {
        for (int64_t i=0; i<args->len; i++)free(argv[i]);
        free(argv);
        return ok;
    }
    int pipes[3][2]= {
        {
            -1,-1
        }, {
            -1,-1
        }, {
            -1,-1
        }
    },err=0;
    pid_t pid=-1;
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attrs;
    bool actions_ready=false,attrs_ready=false;
    pthread_mutex_lock(&fork_lock);
    for (int i=0; i<3 && !err; i++) {
        if (pipe(pipes[i]))err=errno;
        else for (int j=0; j<2; j++) {
            // Keep child sources away from 0/1/2 even if Vela inherited a
            // closed standard descriptor; later close actions must not undo dup2.
            if (pipes[i][j]<3) {
                int moved=fcntl(pipes[i][j],F_DUPFD_CLOEXEC,3);
                if (moved<0) {err=errno;break;}
                close(pipes[i][j]);pipes[i][j]=moved;
            }
            if (fcntl(pipes[i][j],F_SETFD,FD_CLOEXEC)<0)err=errno;
        }
    }
    if (!err) {
        err=posix_spawn_file_actions_init(&actions);
        actions_ready=err==0;
    }
    if (!err) {
        err=posix_spawnattr_init(&attrs);
        attrs_ready=err==0;
    }
    if (!err)err=posix_spawnattr_setflags(&attrs,POSIX_SPAWN_SETPGROUP);
    if (!err)err=posix_spawnattr_setpgroup(&attrs,0);
    for (int i=0; i<3 && !err; i++)err=posix_spawn_file_actions_adddup2(&actions,pipes[i][i==0?0:1],i);
    for (int i=0; i<3 && !err; i++)for (int j=0; j<2 && !err; j++)err=posix_spawn_file_actions_addclose(&actions,pipes[i][j]);
    if (!err)err=posix_spawnp(&pid,argv[0],&actions,&attrs,argv,environ);
    if (actions_ready)posix_spawn_file_actions_destroy(&actions);
    if (attrs_ready)posix_spawnattr_destroy(&attrs);
    pthread_mutex_unlock(&fork_lock);
    for (int64_t i=0; i<args->len; i++)free(argv[i]);
    free(argv);
    if (err) {
        sys_close_pipes(pipes);
        errno=err;
        return sys_errno(e);
    }
    int fd[3]= {
        pipes[0][1],pipes[1][0],pipes[2][0]
    };
    close(pipes[0][0]);
    close(pipes[1][1]);
    close(pipes[2][1]);
    ok=true;
    for (int i=0; i<3; i++)if (fcntl(fd[i],F_SETFL,O_NONBLOCK)<0) {
        ok=sys_errno(e);
        break;
    }
    int64_t pos=0,deadline=sys_now()+timeout,total=0;
    vela_array *data[2]= {
        vela_array_new(&vela_type_byte,4096),vela_array_new(&vela_type_byte,4096)
    };
    int status=0;
    bool reaped=false;
    while (ok) {
        if (fd[0]>=0 && pos==input.len) {
            close(fd[0]);
            fd[0]=-1;
        }
        if (!reaped && fd[0]<0 && fd[1]<0 && fd[2]<0) {
            pid_t got=waitpid(pid,&status,WNOHANG);
            if (got==pid)reaped=true;
            else if (got<0 && errno!=EINTR) {
                ok=sys_errno(e);
                break;
            }
        }
        if (reaped && fd[0]<0 && fd[1]<0 && fd[2]<0)break;
        int64_t left=deadline-sys_now();
        if (left<0) {
            ok=sys_error(e,"process timeout");
            break;
        }
        // Short polls also reap children that close their pipes before exiting.
        struct pollfd ps[3];
        for (int i=0; i<3; i++)ps[i]=(struct pollfd) {
            fd[i],i==0?POLLOUT:POLLIN,0
        };
        int r=poll(ps,3,(int)(left>20?20:left));
        if (r<0) {
            if (errno==EINTR)continue;
            ok=sys_errno(e);
            break;
        }
        for (int i=0; i<3 && ok; i++)if (fd[i]>=0 && ps[i].revents) {
            if (i==0) {
                ssize_t n=sys_write_fd(fd[i],input.data+pos,(size_t)(input.len-pos));
                if (n>0)pos+=n;
                else if (n<0 && errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK) {
                    if (errno==EPIPE) {
                        close(fd[i]);
                        fd[i]=-1;
                    }else ok=sys_errno(e);
                }
            } else {
                uint8_t buf[8192];
                ssize_t n=read(fd[i],buf,sizeof buf);
                if (n>0) {
                    if (n>limit-total) {
                        ok=sys_error(e,"process output limit exceeded");
                        break;
                    }
                    total+=n;
                    for (ssize_t j=0; j<n; j++)vela_array_push(data[i-1],&buf[j]);
                }else if (n==0) {
                    close(fd[i]);
                    fd[i]=-1;
                }else if (errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK)ok=sys_errno(e);
            }
        }
    }
    for (int i=0; i<3; i++)if (fd[i]>=0)close(fd[i]);
    if (!ok) {
        kill(-pid,SIGKILL);
        kill(pid,SIGKILL);
    }
    if (!reaped)while (waitpid(pid,&status,0)<0)if (errno!=EINTR)break;
    if (ok) {
        *out=vela_array_new(&vela_type_str,3);
        vela_str vals[3]= {
            vela_from_int(WIFSIGNALED(status)?128+WTERMSIG(status):WEXITSTATUS(status)),str_from((const char*)data[0]->data,(size_t)data[0]->len),str_from((const char*)data[1]->data,(size_t)data[1]->len)
        };
        for (int i=0; i<3; i++) {
            sys_push(*out,vals[i]);
            vela_str_release(vals[i]);
        }
    }
    vela_array_release(data[0]);
    vela_array_release(data[1]);
    return ok;
}
// Legacy os.run/output share the process fake rather than escaping its scope.
static bool sys_legacy_process(vela_array *args,int64_t *code,vela_str *e,vela_str *captured,bool *handled) {
    lock_fakes();*handled=sys_processes!=NULL;unlock_fakes();
    if (!*handled) return false;
    if (args->len==0 || sys_word(args,0).len==0) return sys_error(e,"process needs a program");
    for (int64_t i=0;i<args->len;i++) {vela_str a=sys_word(args,i);if (a.len && memchr(a.data,0,(size_t)a.len)) return sys_error(e,"argument contains a zero byte");}
    vela_array *out=NULL;
    bool ok=sys_process_fake(args,VELA_STR("",0),67108864,&out,e,handled);
    if (!*handled || !ok)return ok;
    vela_str number=sys_word(out,0);
    char *n=c_path(number);
    char *end=NULL;
    errno=0;
    long long status=n?strtoll(n,&end,10):-1;
    if (!n || errno || !end || *end || status<0 || status>255) {
        free(n);
        vela_array_release(out);
        return sys_error(e,"invalid fake exit status");
    }
    free(n);
    *code=status;
    if (captured) {
        *captured=sys_word(out,1);
        vela_str_retain(*captured);
    }
    if (!captured) vela_os_write(sys_word(out,1));
    vela_str stderr_text=sys_word(out,2);
    if (stderr_text.len) fwrite(stderr_text.data,1,(size_t)stderr_text.len,stderr);
    vela_array_release(out);
    return true;
}
// Directory fakes use existing files entries; trailing slash keys denote empty dirs.
static vela_str sys_dir_prefix(vela_str path) {
    while (path.len>1 && path.data[path.len-1]=='/')path.len--;
    if (sys_is(path,".") || path.len==0)return VELA_STR("",0);
    if (sys_is(path,"/"))return VELA_STR("/",1);
    return vela_str_concat(path,VELA_STR("/",1));
}
static int64_t sys_fake_kind(vela_str path) {
    vela_str prefix=sys_dir_prefix(path);
    if (prefix.len==0 || sys_is(prefix,"/"))return 2;
    bool file=vela_map_find(fake_files,&path)!=NULL;
    vela_array *keys=vela_map_keys(fake_files);
    int64_t kind=file?1:0;
    for (int64_t i=0; i<keys->len; i++) {
        vela_str k=sys_word(keys,i);
        if (k.len>=prefix.len && !memcmp(k.data,prefix.data,(size_t)prefix.len)) {
            kind=2;
            break;
        }
    }
    vela_array_release(keys);
    vela_str_release(prefix);
    return kind;
}
static int sys_str_cmp(const void *pa,const void *pb) {
    vela_str a=*(const vela_str*)pa,b=*(const vela_str*)pb;
    int64_t n=a.len<b.len?a.len:b.len;
    int c=memcmp(a.data,b.data,(size_t)n);
    return c?c:(a.len>b.len)-(a.len<b.len);
}
bool vela_sys_kind(vela_str path,int64_t *o,vela_str *e) {
    char *p=c_path(path);
    if (!p || !*p) {
        free(p);
        return sys_error(e,"invalid path");
    }
    if (files_faked) {
        free(p);
        lock_fakes();
        *o=sys_fake_kind(path);
        unlock_fakes();
        return true;
    }
    struct stat s;
    int r=lstat(p,&s);
    free(p);
    if (r) {
        if (errno==ENOENT || errno==ENOTDIR) {
            *o=0;
            return true;
        }
        return sys_errno(e);
    }
    *o=S_ISDIR(s.st_mode)?2:S_ISLNK(s.st_mode)?3:1;
    return true;
}
bool vela_sys_list(vela_str path,vela_array **o,vela_str *e) {
    char *p=c_path(path);
    if (!p || !*p) {
        free(p);
        return sys_error(e,"invalid path");
    }
    vela_array *out=vela_array_new(&vela_type_str,8);
    if (files_faked) {
        free(p);
        lock_fakes();
        if (sys_fake_kind(path)!=2) {
            unlock_fakes();
            vela_array_release(out);
            return sys_error(e,"not a directory");
        }
        vela_str prefix=sys_dir_prefix(path);
        vela_array *keys=vela_map_keys(fake_files);
        for (int64_t i=0; i<keys->len; i++) {
            vela_str k=sys_word(keys,i);
            if (k.len<=prefix.len || memcmp(k.data,prefix.data,(size_t)prefix.len))continue;
            int64_t end=prefix.len;
            while (end<k.len && k.data[end]!='/')end++;
            if (end==prefix.len)continue;
            vela_str name= {
                k.obj,k.data+prefix.len,end-prefix.len
            };
            bool seen=false;
            for (int64_t j=0; j<out->len; j++)if (sys_eq(sys_word(out,j),name))seen=true;
            if (!seen)sys_push(out,name);
        }
        vela_array_release(keys);
        vela_str_release(prefix);
        unlock_fakes();
    }else {
        DIR *d=opendir(p);
        free(p);
        if (!d) {
            vela_array_release(out);
            return sys_errno(e);
        }
        errno=0;
        struct dirent *ent;
        while ((ent=readdir(d))) {
            if (!strcmp(ent->d_name,".") || !strcmp(ent->d_name,".."))continue;
            vela_str n=str_from(ent->d_name,strlen(ent->d_name));
            sys_push(out,n);
            vela_str_release(n);
        }
        int saved=errno;
        closedir(d);
        if (saved) {
            vela_array_release(out);
            errno=saved;
            return sys_errno(e);
        }
    }
    qsort(out->data,(size_t)out->len,sizeof(vela_str),sys_str_cmp);
    *o=out;
    return true;
}
bool vela_sys_mkdir(vela_str path,vela_unit *o,vela_str *e) {
    char *p=c_path(path);
    if (!p || !*p) {
        free(p);
        return sys_error(e,"invalid path");
    }
    *o=0;
    if (files_faked) {
        free(p);
        lock_fakes();
        if (sys_fake_kind(path)!=0) {
            unlock_fakes();
            return sys_error(e,"path exists");
        }
        vela_str trimmed=path;
        while (trimmed.len>1 && trimmed.data[trimmed.len-1]=='/')trimmed.len--;
        int64_t slash=-1;
        for (int64_t i=0; i<trimmed.len; i++)if (trimmed.data[i]=='/')slash=i;
        vela_str parent=slash<0?VELA_STR(".",1):slash==0?VELA_STR("/",1):(vela_str) {
            path.obj,path.data,slash
        };
        if (sys_fake_kind(parent)!=2) {
            unlock_fakes();
            return sys_error(e,"parent is not a directory");
        }
        vela_str key=sys_dir_prefix(path),empty=VELA_STR("",0);
        vela_str_share(key);
        vela_map_unique(&fake_files);
        vela_map_set(fake_files,&key,&empty);
        unlock_fakes();
        return true;
    }
    int r=mkdir(p,0777);
    free(p);
    return r==0 || sys_errno(e);
}
