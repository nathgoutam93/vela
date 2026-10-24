// Reflected CRC-32: the same table and streaming update as the Vela program.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc,char **argv){
    size_t n=argc>1?(size_t)strtoull(argv[1],NULL,10):4194304;
    int rounds=argc>2?atoi(argv[2]):32;
    unsigned char *data=malloc(n?n:1);if(!data)return 1;memset(data,'a',n);
    uint32_t table[256];
    for(unsigned i=0;i<256;i++){
        uint32_t c=i;
        for(int bit=0;bit<8;bit++)c=(c&1)?((c>>1)^0xedb88320u):(c>>1);
        table[i]=c;
    }
    uint32_t result=0;
    for(int r=0;r<rounds;r++){
        uint32_t c=~result;
        for(size_t i=0;i<n;i++)c=(c>>8)^table[(c^data[i])&255u];
        result=~c;
    }
    printf("%u\n",result);free(data);return 0;
}
