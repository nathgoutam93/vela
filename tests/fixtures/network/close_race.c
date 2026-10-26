// Compiled with a temporary runtime whose net_read receive call is gated here.
// This deterministically closes an alias after a read pins the descriptor.
#include "vela_rt.c"
#include <assert.h>

static pthread_mutex_t gate_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_condition=PTHREAD_COND_INITIALIZER;
static int entered=0,proceed=0,completed=0;

static ssize_t net_test_recv(sys_fd fd,void *data,size_t size,int flags) {
    pthread_mutex_lock(&gate_lock);
    int ticket=++entered;
    pthread_cond_broadcast(&gate_condition);
    while (proceed<ticket) pthread_cond_wait(&gate_condition,&gate_lock);
    pthread_mutex_unlock(&gate_lock);
    return recv(fd,data,size<4?size:4,flags);
}

typedef struct { vela_io_handle *handle; bool ok; vela_str data; } Job;
static void *read_once(void *argument) {
    Job *job=argument;
    vela_str error=VELA_STR("",0);
    job->ok=vela_sys_net_read(job->handle,4096,&job->data,&error);
    vela_str_release(error);
    pthread_mutex_lock(&gate_lock);completed++;pthread_cond_broadcast(&gate_condition);pthread_mutex_unlock(&gate_lock);
    return NULL;
}

int main(void) {
    for (int round=0;round<32;round++) {
        int pair[2];assert(socketpair(AF_UNIX,SOCK_STREAM,0,pair)==0);
        assert(sys_socket_flags(pair[0])==0);
        vela_io_handle *handle=sys_handle(pair[0],1,AF_UNIX,0,VELA_STR("",0),NULL,-1,1000);
        const unsigned char payload[]={65,0,255,90};
        assert(send(pair[1],payload,sizeof payload,0)==(ssize_t)sizeof payload);
        assert(send(pair[1],payload,sizeof payload,0)==(ssize_t)sizeof payload);
        Job jobs[]={{handle,false,VELA_STR("",0)},{handle,false,VELA_STR("",0)}};
        entered=0;proceed=0;completed=0;
        pthread_t readers[2];
        for (int i=0;i<2;i++) assert(pthread_create(&readers[i],NULL,read_once,&jobs[i])==0);
        pthread_mutex_lock(&gate_lock);
        while (entered<2) pthread_cond_wait(&gate_condition,&gate_lock);
        pthread_mutex_unlock(&gate_lock);

        vela_str error=VELA_STR("",0);vela_unit unit=0;
        assert(vela_sys_net_close(handle,&unit,&error));
        // Every new operation must fail while the original receive is paused.
        vela_str unused=VELA_STR("",0);
        assert(!vela_sys_net_read(handle,1,&unused,&error));vela_str_release(error);
        error=VELA_STR("",0);
        int64_t written=0;
        assert(!vela_sys_net_write(handle,VELA_STR("x",1),&written,&error));vela_str_release(error);
        // Force descriptor reuse if close incorrectly invalidated the pinned fd.
        int pressure[32];
        for (int i=0;i<32;i++) {pressure[i]=socket(AF_INET,SOCK_STREAM,0);assert(pressure[i]>=0);}
        pthread_mutex_lock(&gate_lock);proceed=1;pthread_cond_broadcast(&gate_condition);
        while (completed<1) pthread_cond_wait(&gate_condition,&gate_lock);
        pthread_mutex_unlock(&gate_lock);
        unsigned char byte;
        // One completed operation must not close the other operation's socket.
        assert(recv(pair[1],&byte,1,MSG_DONTWAIT)==-1 && (errno==EAGAIN || errno==EWOULDBLOCK));
        pthread_mutex_lock(&gate_lock);proceed=2;pthread_cond_broadcast(&gate_condition);pthread_mutex_unlock(&gate_lock);
        for (int i=0;i<2;i++) {
            assert(pthread_join(readers[i],NULL)==0);
            assert(jobs[i].ok && jobs[i].data.len==(int64_t)sizeof payload && !memcmp(jobs[i].data.data,payload,sizeof payload));
            vela_str_release(jobs[i].data);
        }
        // The operation finishing must close the underlying connection even
        // though the closed handle itself remains alive until below.
        assert(recv(pair[1],&byte,1,0)==0);
        for (int i=0;i<32;i++) close(pressure[i]);
        close(pair[1]);vela_handle_release(handle);
    }
    puts("close race passed");
    return 0;
}
