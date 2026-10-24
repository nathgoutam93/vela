// SHA-256, FIPS 180-4. Same schedule and round loop as the Vela version.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const uint32_t constants[64] = {0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};
static uint32_t rotr(uint32_t x, unsigned n) { return (x >> n) | (x << (32-n)); }
static void digest(const unsigned char *data, size_t len, uint32_t state[8]) {
    const uint32_t initial[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au, 0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
    memcpy(state, initial, sizeof initial);
    uint32_t words[64];
    size_t padded = ((len+9+63)/64)*64;
    uint64_t bit_length = (uint64_t)len << 3;
    for (size_t block=0;block<padded/64;block++) {
        for (size_t i=0;i<64;i++) {
            if (i<16) {
                uint32_t word=0;
                for (size_t j=0;j<4;j++) {
                    size_t at=block*64+i*4+j;
                    uint32_t b=0;
                    if (at<len) b=data[at];
                    else if (at==len) b=128;
                    else if (at>=padded-8) b=(uint32_t)((bit_length >> ((padded-1-at)*8)) & 255);
                    word=(word<<8)|b;
                }
                words[i]=word;
            } else {
                uint32_t x=words[i-15],y=words[i-2];
                uint32_t s0=rotr(x,7)^rotr(x,18)^(x>>3);
                uint32_t s1=rotr(y,17)^rotr(y,19)^(y>>10);
                words[i]=words[i-16]+s0+words[i-7]+s1;
            }
        }
        uint32_t a=state[0],b=state[1],c=state[2],d=state[3],e=state[4],f=state[5],g=state[6],h=state[7];
        for (size_t i=0;i<64;i++) {
            uint32_t s1=rotr(e,6)^rotr(e,11)^rotr(e,25);
            uint32_t choice=(e&f)^(~e&g);
            uint32_t t1=h+s1+choice+constants[i]+words[i];
            uint32_t s0=rotr(a,2)^rotr(a,13)^rotr(a,22);
            uint32_t majority=(a&b)^(a&c)^(b&c);
            uint32_t t2=s0+majority;
            h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
        }
        state[0]+=a;state[1]+=b;state[2]+=c;state[3]+=d;
        state[4]+=e;state[5]+=f;state[6]+=g;state[7]+=h;
    }
}
int main(int argc,char **argv) {
    size_t n=argc>1?(size_t)strtoull(argv[1],NULL,10):1048576;
    int rounds=argc>2?atoi(argv[2]):32;
    unsigned char *data=malloc(n?n:1);if(!data)return 1;memset(data,'a',n);
    char result[65]={0};size_t prefix=0;
    for(int r=0;r<rounds;r++) {
        unsigned char *message=malloc(n+prefix+1);if(!message)return 1;
        memcpy(message,result,prefix);memcpy(message+prefix,data,n);
        uint32_t state[8];digest(message,n+prefix,state);free(message);
        for(int i=0;i<8;i++)snprintf(result+i*8,9,"%08x",state[i]);
        prefix=64;
    }
    puts(result);free(data);return 0;
}
