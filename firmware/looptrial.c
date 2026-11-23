/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "looptrial.h"
#include <stdbool.h>

enum { IDLE, RUNNING, DONE, CANCELLED };
enum { CAPACITY = 64, PAGE = 6, HISTORY = 8 };
typedef struct {
    uint32_t token, target, period, length, gain, start;
    volatile unsigned state, count;
    struct { uint32_t ms, value; } rows[CAPACITY];
} experiment;
static experiment run;
static volatile uint32_t clock_ms;
static uint32_t identity, previous[HISTORY], previous_next;
static volatile uint32_t gain;

enum { LIVE_PERIOD_MS = 50, LIVE_CAPACITY = 32, LIVE_PAGE = 4 };
typedef struct { uint32_t target, milli, gain; } observation;
static volatile observation live[LIVE_CAPACITY];
static volatile uint32_t live_seq;
static uint32_t live_ticks, idle_milli;

void lt_init(uint32_t tag) {
    identity = tag;
    gain = 2;
}

static void step_trial(uint32_t now) {
    if (run.state != RUNNING) return;
    unsigned i = run.count;
    uint32_t elapsed = now - run.start;
    if (elapsed < (i + 1) * run.period) return;
    /* Fixed-point first-order software plant. Every action starts at zero. */
    uint32_t y = i ? run.rows[i-1].value : 0;
    uint32_t error = run.target * 1000 - y;
    run.rows[i].value = y + (error * run.gain + 15) / 16;
    run.rows[i].ms = elapsed;
    run.count = i + 1;
    if (run.count == run.length) run.state = DONE;
}

void lt_tick(void) {
    bool taking_step = run.state == RUNNING;
    step_trial(++clock_ms);
    if (++live_ticks != LIVE_PERIOD_MS) return;
    live_ticks = 0;
    uint32_t seq = live_seq + 1;
    observation sample;
    sample.gain = gain;
    if (taking_step) {
        sample.target = run.target;
        sample.milli = run.count ? run.rows[run.count - 1].value : 0;
    } else {
        /* A repeating bench reference makes parameter changes visible without an actuator. */
        sample.target = ((seq - 1) / 20) % 2 ? 120 : 20;
        int32_t difference = (int32_t)(sample.target * 1000) - (int32_t)idle_milli;
        idle_milli = (uint32_t)((int32_t)idle_milli + difference * (int32_t)sample.gain / 16);
        sample.milli = idle_milli;
    }
    live[seq % LIVE_CAPACITY] = sample;
    live_seq = seq;
}

typedef struct { lt_send send; void *port; } output;
static void string(output o, const char *s) {
    while (*s) o.send(o.port, *s++);
}
static void number(output o, uint32_t n) {
    char digits[10];
    unsigned count = 0;
    do {
        digits[count++] = (char)('0' + n % 10);
        n /= 10;
    } while (n);
    while (count) o.send(o.port, digits[--count]);
}
static void field(output o, uint32_t n) {
    o.send(o.port, ' ');
    number(o, n);
}
static bool integer(char **s, uint32_t *n) {
    char *p = *s;
    uint32_t v = 0;
    if (*p < '0' || *p > '9') return false;
    do {
        unsigned d = (unsigned)(*p++ - '0');
        if (v > (UINT32_MAX - d) / 10) return false;
        v = v * 10 + d;
    } while (*p >= '0' && *p <= '9');
    *s = p;
    *n = v;
    return true;
}
static bool valid(uint32_t n, unsigned low, unsigned high) {
    return n >= low && n <= high;
}

static void telemetry(output o, uint32_t cursor) {
    observation page[LIVE_PAGE];
    uint32_t first, n;
    /* Copy before slow UART output. Retry only if an interrupt recycled a slot
       while copying the oldest retained page. No interrupts are disabled. */
    do {
        uint32_t latest = live_seq;
        if (cursor > latest) { string(o,"ERR clock_reset"); return; }
        if (cursor == latest) { string(o,"OK 0 0"); return; }
        first = cursor ? cursor + 1 : latest;
        if (latest - first >= LIVE_CAPACITY) first = latest - LIVE_PAGE + 1;
        n = latest - first + 1;
        if (n > LIVE_PAGE) n = LIVE_PAGE;
        for (unsigned i = 0; i < n; ++i) page[i] = live[(first+i) % LIVE_CAPACITY];
    } while (live_seq - first >= LIVE_CAPACITY);
    string(o,"OK"); field(o,first); field(o,n);
    for (unsigned i = 0; i < n; ++i) {
        field(o,page[i].target); field(o,page[i].milli); field(o,page[i].gain);
    }
}
static const char *start(uint32_t *a) {
    uint32_t token = a[0], target = a[1], period = a[2], length = a[3], expected = a[4];
    if (!token || !valid(target,1,1000) || !valid(period,10,100) || !valid(length,4,CAPACITY))
        return "ERR range";
    if (run.token == token) {
        if (run.target != target || run.period != period || run.length != length || run.gain != expected)
            return "ERR conflict";
        return "OK";
    }
    if (run.state == RUNNING) return "ERR busy";
    for (unsigned i=0; i<HISTORY; ++i)
        if (previous[i] == token) return "ERR expired";
    if (gain != expected) return "ERR readback_mismatch";
    previous[previous_next++ % HISTORY] = run.token;
    run.token = token;
    run.target = target;
    run.period = period;
    run.length = length;
    run.gain = gain;
    run.start = clock_ms;
    run.count = 0;
    run.state = RUNNING;
    return "OK";
}
static void command(char *line, output o) {
    uint32_t seq, args[5];
    unsigned argc = 0;
    if (*line++ != '@' || !integer(&line,&seq) || *line++ != ' ' || !*line) return;
    char cmd = *line++;
    o.send(o.port, '@');
    number(o, seq);
    o.send(o.port, ' ');
    while (*line) {
        if (*line++ != ' ' || argc == 5 || !integer(&line, &args[argc])) {
            string(o,"ERR syntax\n");
            return;
        }
        ++argc;
    }
    if (cmd == 'H' && argc == 0) {
        string(o, "OK LT1 bluepill-step 0.2.0");
        field(o, identity);
    } else if (cmd == 'T' && argc == 1) {
        telemetry(o,args[0]);
    } else if (cmd == 'R' && argc == 0) {
        string(o, "OK"); field(o,gain);
    } else if (cmd == 'W' && argc == 1) {
        if (!valid(args[0],1,16)) string(o,"ERR range");
        else if (run.state == RUNNING) string(o,"ERR busy");
        else { gain = args[0]; string(o,"OK"); field(o,gain); }
    } else if (cmd == 'S' && argc == 5) {
        string(o,start(args));
    } else if (((cmd == 'Q' || cmd == 'X') && argc == 1) || (cmd == 'F' && argc == 2)) {
        if (!args[0] || args[0] != run.token) string(o,"ERR unknown_trial");
        else if (cmd == 'F') {
            unsigned offset = args[1], count = run.count;
            if (offset >= count) string(o,"ERR range");
            else {
                unsigned n = count - offset;
                if (n > PAGE) n = PAGE;
                string(o,"OK"); field(o,offset); field(o,n);
                for (unsigned i=offset; i<offset+n; ++i) {
                    field(o,run.rows[i].ms);
                    field(o,run.rows[i].value);
                }
            }
        } else {
            if (cmd == 'X' && run.state == RUNNING) run.state = CANCELLED;
            string(o,"OK"); field(o,run.state); field(o,run.count); field(o,run.gain);
        }
    } else string(o,"ERR command");
    o.send(o.port,'\n');
}
void lt_receive(lt_decoder *d, char byte, lt_send send, void *port) {
    if (byte == '\n') {
        if (!d->discard && d->used) {
            d->line[d->used] = 0;
            command(d->line, (output){send,port});
        }
        d->used = 0;
        d->discard = 0;
    } else if (byte != '\r') {
        if ((unsigned char)byte < 32 || (unsigned char)byte > 126 || d->used == sizeof d->line - 1)
            d->discard = 1;
        else if (!d->discard) d->line[d->used++] = byte;
    }
}
