/* SPDX-License-Identifier: GPL-3.0-or-later */
ENTRY(reset_handler)
MEMORY {
    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 64K
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 20K
}
_stack_top = ORIGIN(RAM) + LENGTH(RAM);
SECTIONS {
    .vectors : { KEEP(*(.vectors)) } > FLASH
    .text : { *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH
    .data : {
        _data_start = .; *(.data*) . = ALIGN(4); _data_end = .;
    } > RAM AT >FLASH
    _data_load = LOADADDR(.data);
    .bss (NOLOAD) : {
        _bss_start = .; *(.bss*) *(COMMON) . = ALIGN(4); _bss_end = .;
    } > RAM
    ASSERT(_bss_end + 1024 <= _stack_top, "Less than 1 KiB of stack")
}
