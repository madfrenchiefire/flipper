; pinwiggle: minimal FX2 firmware for probing the iShow board.
;
; The host writes a mailbox in RAM with the FX2's built-in 0xA0 request
; (which keeps working while this program runs, because it never takes
; over the USB connection). This loop copies the mailbox to the port
; registers forever:
;
;   0x3F00  OEA   port A direction (1 = output)
;   0x3F01  IOA   port A output value
;   0x3F02  OED   port D direction
;   0x3F03  IOD   port D output value
;   0x3F04  heartbeat, incremented every loop (proves the program runs)
;   0x3F05  port A pins as read back
;   0x3F06  port D pins as read back

        .module pinwiggle
        .area   CSEG (ABS,CODE)
        .org    0x0000

IOA = 0x80
IOD = 0xB0
OEA = 0xB2
OED = 0xB5

start:
        mov     dptr,#0x3F00
        movx    a,@dptr
        mov     OEA,a
        inc     dptr
        movx    a,@dptr
        mov     IOA,a
        inc     dptr
        movx    a,@dptr
        mov     OED,a
        inc     dptr
        movx    a,@dptr
        mov     IOD,a
        inc     dptr
        movx    a,@dptr         ; heartbeat++
        inc     a
        movx    @dptr,a
        inc     dptr
        mov     a,IOA           ; read back port A
        movx    @dptr,a
        inc     dptr
        mov     a,IOD           ; read back port D
        movx    @dptr,a
        sjmp    start
