#include <stdint.h>
#include <stddef.h>
long c_long(long x){return x;}
size_t c_size(size_t x){return x;}
unsigned long c_ulong(unsigned long x){return x;}
int pointer_size(void){return sizeof(void*);}
long callback(long (*fn)(long),long x){return fn(x);}
