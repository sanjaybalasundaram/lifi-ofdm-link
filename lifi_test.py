import serial, time

s = serial.Serial('/dev/cu.usbserial-0001', 1200, timeout=2)
time.sleep(1)
s.reset_input_buffer()

msg = b'Hello Li-Fi from Sanjay'
ok = 0
trials = 10
for i in range(trials):
    s.reset_input_buffer()
    s.write(msg)
    time.sleep(0.5)
    got = s.read(len(msg))
    print(f'{i+1}: {got}')
    ok += (got == msg)

print(f'Success: {ok}/{trials}')
