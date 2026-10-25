// Platform thread primitives. WASI preview 1 executes tasks sequentially.
#ifndef VELA_THREADS_H
#define VELA_THREADS_H
#if defined(__wasi__)
#define pthread_mutex_t vela_mutex
#define pthread_cond_t vela_cond
#define pthread_t vela_thread
typedef int vela_mutex;
typedef int vela_cond;
typedef int vela_thread;
#define PTHREAD_MUTEX_INITIALIZER 0
#define PTHREAD_COND_INITIALIZER 0
static inline int pthread_mutex_init(pthread_mutex_t *m, const void *a) { (void)m; (void)a; return 0; }
static inline int pthread_mutex_destroy(pthread_mutex_t *m) { (void)m; return 0; }
static inline int pthread_mutex_lock(pthread_mutex_t *m) { (void)m; return 0; }
static inline int pthread_mutex_unlock(pthread_mutex_t *m) { (void)m; return 0; }
static inline int pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m) { (void)c; (void)m; return 0; }
static inline int pthread_cond_signal(pthread_cond_t *c) { (void)c; return 0; }
static inline int pthread_cond_broadcast(pthread_cond_t *c) { (void)c; return 0; }
static inline int pthread_create(pthread_t *t, const void *a, void *(*f)(void *), void *p) { (void)t; (void)a; (void)f; (void)p; return 1; }
static inline int pthread_detach(pthread_t t) { (void)t; return 0; }
#define flockfile(f) ((void)(f))
#define funlockfile(f) ((void)(f))
#else
#include <pthread.h>
#endif
#endif
