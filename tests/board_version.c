/* Two ordinary, immutable builds of a demo plugin. */
#ifndef BOARD_VERSION
#define BOARD_VERSION 1
#endif
int board_version(void) {
    return BOARD_VERSION;
}
