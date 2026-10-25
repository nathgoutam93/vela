#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <windows.h>
#include <io.h>
#include <fcntl.h>
int main(int argc,char **argv) {
    _setmode(_fileno(stdin),_O_BINARY);_setmode(_fileno(stdout),_O_BINARY);_setmode(_fileno(stderr),_O_BINARY);
    if(argc>1 && !strcmp(argv[1],"args")){for(int i=2;i<argc;i++)printf("%s\n",argv[i]);return 0;}
    if(argc>1 && !strcmp(argv[1],"sleep")){Sleep(10000);return 0;}
    if(argc>1 && !strcmp(argv[1],"close")){_close(0);fputs("done",stdout);return 0;}
    char bytes[8192];size_t n;
    while((n=fread(bytes,1,sizeof bytes,stdin))){fwrite(bytes,1,n,stdout);if(!(argc>1 && !strcmp(argv[1],"stdin")))fwrite(bytes,1,n,stderr);}
    return argc>1 && !strcmp(argv[1],"stdin")?0:7;
}
