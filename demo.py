"""Li-Fi demo: runs the light-on / light-blocked / light-on sequence for a video."""
import serial, time

PORT = '/dev/cu.usbserial-0001'
BAUD = 9600
MSG = b'Hello Li-Fi from Sanjay'
TRIALS = 10


def countdown(text, seconds):
    print(f'\n>>> {text}')
    input('    Press Enter when ready...')
    for s in range(seconds, 0, -1):
        print(f'    starting in {s}...', end='\r', flush=True)
        time.sleep(1)
    print(' ' * 30, end='\r')


def run(s, title):
    print(f'\n=== {title} ===')
    ok = 0
    for i in range(TRIALS):
        s.reset_input_buffer()
        s.write(MSG)
        s.flush()
        got = s.read(len(MSG))
        good = got == MSG
        ok += good
        print(f'  {i+1:>2}: {"OK  " if good else "FAIL"} {got}')
        time.sleep(0.6)
    print(f'  Result: {ok}/{TRIALS} messages received through light')
    return ok


s = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(1)
print('Li-Fi link demo  |  LED -> light -> photodiode -> LM393 -> UART')

countdown('Test 1: LIGHT ON (LED shining on photodiode)', 3)
run(s, 'LIGHT ON')

countdown('Test 2: BLOCK THE LIGHT NOW (put paper between LED and photodiode)', 6)
run(s, 'LIGHT BLOCKED')

countdown('Test 3: REMOVE THE PAPER NOW', 6)
run(s, 'LIGHT ON AGAIN')

s.close()
print('\nDemo complete: data flows only when the light path is open.')
