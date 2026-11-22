/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef LOOPTRIAL_H
#define LOOPTRIAL_H
#include <stdint.h>

/* Give each byte stream its own decoder. The two ports share one object. */
typedef struct {
    char line[80];
    unsigned used, discard;
} lt_decoder;
typedef void (*lt_send)(void *port, char byte);
void lt_init(uint32_t identity_tag);
void lt_receive(lt_decoder *decoder, char byte, lt_send send, void *port);
/* Run from a 1 ms interrupt, including while a transport is sending data. */
void lt_tick(void);
#endif
