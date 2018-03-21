import pyb
import gc
from array import array

class Photometry():

    def __init__(self, sampling_rate=256, buffer_size=256, oversampling_rate=1e6, 
                 analog_pin_1='X5', analog_pin_2='X6', digital_pin_1='X1', digital_pin_2='X2'):
        self.buffer_size = buffer_size
        self.sampling_rate = sampling_rate
        self.ADC1 = pyb.ADC(analog_pin_1)
        self.ADC2 = pyb.ADC(analog_pin_2)
        self.DI1 = pyb.Pin(digital_pin_1, pyb.Pin.IN, pyb.Pin.PULL_DOWN)
        self.DI2 = pyb.Pin(digital_pin_2, pyb.Pin.IN, pyb.Pin.PULL_DOWN)
        self.ovs_buffer = array('H',[0]*64) # Oversampling buffer
        self.ovs_timer = pyb.Timer(2)       # Oversampling timer.
        self.ovs_timer.init(freq=oversampling_rate)
        self.sampling_timer = pyb.Timer(3)
        self.sample_buffers = (array('H',[0]*(buffer_size+2)), array('H',[0]*(buffer_size+2)))
        self.buffer_data_mv = (memoryview(self.sample_buffers[0])[:-2], 
                               memoryview(self.sample_buffers[1])[:-2])
        self.usb_serial = pyb.USB_VCP()

    def start(self):
        #Start acquisition.
        self.write_buffer = 0 # Buffer to write data to.
        self.send_buffer  = 1 # Buffer to send data from.
        self.write_index  = 0 # Buffer index to write new data to. 
        self.buffer_ready = False # Set to True when full buffer is ready to send.
        gc.disable()
        self.sampling_timer.init(freq=self.sampling_rate)
        self.sampling_timer.callback(self._timer_ISR)

    def stop(self):
        # Stop aquisition
        self.sampling_timer.deinit()
        gc.enable()

    @micropython.native
    def _timer_ISR(self, t):
        # Read a sample to the buffer using oversampling and averaging.
        self.ADC1.read_timed(self.ovs_buffer, self.ovs_timer)
        self.sample_buffers[self.write_buffer][self.write_index] = sum(self.ovs_buffer) >> 3
        if self.DI1.value(): 
            self.sample_buffers[self.write_buffer][self.write_index] += 0x8000
        self.write_index += 1
        self.ADC2.read_timed(self.ovs_buffer, self.ovs_timer)
        self.sample_buffers[self.write_buffer][self.write_index] = sum(self.ovs_buffer) >> 3
        if self.DI2.value(): 
            self.sample_buffers[self.write_buffer][self.write_index] += 0x8000
        # Store digital input signal in highest bit of sample.
        self.write_index = (self.write_index + 1) % self.buffer_size
        if self.write_index == 0: # Buffer full, switch buffers.
            self.write_buffer = 1 - self.write_buffer
            self.send_buffer  = 1 - self.send_buffer
            self.buffer_ready = True

    def _send_buffer(self):
        # Send full buffer to host computer. Format of the serial chunks sent to the computer: 
        # buffer[:-2] = data, buffer[-2] = checksum, buffer[-1] = 0.
        self.sample_buffers[self.send_buffer][-2] = sum(self.buffer_data_mv[self.send_buffer]) # Checksum
        self.usb_serial.send(self.sample_buffers[self.send_buffer])
        self.buffer_ready = False

    def run(self):
        # Start acquisition, stream data to computer, wait for ctrl+c over serial to stop. 
        self.start()
        try:
            while True:
                if self.buffer_ready:
                    self._send_buffer()
        except KeyboardInterrupt:
            self.stop()