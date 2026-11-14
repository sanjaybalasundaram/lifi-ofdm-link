import serial, time

msg = b'Hello Li-Fi from Sanjay'
for baud in [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]:
    s = serial.Serial('/dev/cu.usbserial-0001', baud, timeout=2)
    time.sleep(1)
    s.reset_input_buffer()
    ok = 0
    for i in range(20):
        s.reset_input_buffer()
        s.write(msg)
        s.flush()
        ok += (s.read(len(msg)) == msg)
    s.close()
    print(f'{baud:>6} baud: {ok}/20 correct')
