import time as utime
import machine
from machine import Pin

from OV5642_reg import *

OV5642=1

MAX_FIFO_SIZE=0x7FFFFF
ARDUCHIP_FRAMES=0x01
ARDUCHIP_TIM=0x03
VSYNC_LEVEL_MASK=0x02
ARDUCHIP_TRIG=0x41
CAP_DONE_MASK=0x08

OV5642_CHIPID_HIGH=0x300a
OV5642_CHIPID_LOW=0x300b

OV5642_320x240  =0
OV5642_640x480  =1
OV5642_1024x768 =2
OV5642_1280x960 =3
OV5642_1600x1200=4
OV5642_2048x1536=5
OV5642_2592x1944=6
OV5642_1920x1080=7

high_quality   =0
default_quality=1
low_quality    =2

BMP =0
JPEG=1
RAW =2

class ArducamClass(object):
    def __init__(self,Type):
        self.CameraMode=JPEG
        self.CameraType=Type
        self.SPI_CS=machine.Pin(5, machine.Pin.OUT)
        self.spi = machine.SPI(2, baudrate=4000000, sck=Pin(21), mosi=Pin(18), miso=Pin(19))
        self.i2c = machine.SoftI2C(scl=Pin(23), sda=Pin(22), freq=1000000)
        #self.i2c.start()
        #self.i2c.init(0, frequency=1000000)
        #while not self.i2c.try_lock():
        #    pass
        utime.sleep(0.1)
        appareils = self.i2c.scan()
        print("Appareils I2C detectes:", [hex(a) for a in appareils])
        if 0x3C in appareils:
            self.i2c_address = 0x3C
        else:
            # Adresse standard de l'OV5642 : on l'utilise quand meme,
            # au cas ou le scan aurait rate l'appareil (signal limite).
            print("[!] 0x3C non trouve dans le scan, utilisation quand meme de 0x3C.")
            self.i2c_address = 0x3C
        print("I2C Address utilisee:", hex(self.i2c_address))
        self.Spi_write(0x07,0x80)
        utime.sleep(0.1)
        self.Spi_write(0x07,0x00)
        utime.sleep(0.1)
        
    def Camera_Detection(self):
        while True:
            if self.CameraType==OV5642:
                self.I2cAddress=0x3c
                #utime.sleep(0.1)
                self.wrSensorReg16_8(0xff,0x01)
                utime.sleep(1)
                id_h=self.rdSensorReg16_8(OV5642_CHIPID_HIGH)
                id_l=self.rdSensorReg16_8(OV5642_CHIPID_LOW)
                if((id_h==0x56)and(id_l==0x42)):
                    print('CameraType is OV5642')
                    break
                else:
                    print('Can\'t find OV5642 module')
            utime.sleep(1)
            
    def Set_Camera_mode(self,mode):
        self.CameraMode=mode
    
    def wrSensorReg16_8(self,addr,val):
        buffer=bytearray(3)
        buffer[0]=(addr>>8)&0xff
        buffer[1]=addr&0xff
        buffer[2]=val
        #print(buffer)
        self.iic_write(buffer)
    
    def rdSensorReg16_8(self,addr):
        buffer=bytearray(2)
        rt=bytearray(1)
        buffer[0]=(addr>>8)&0xff
        buffer[1]=addr&0xff
        self.iic_write(buffer)
        self.iic_readinto(rt)
        return rt[0]
    
    def wrSensorReg8_8(self,addr,val):
        buffer=bytearray(2)
        buffer[0]=addr
        buffer[1]=val
        self.iic_write(buffer)
        
    def iic_write(self, buf, *, start=0, end=None):
        self.i2c.writeto(self.i2c_address, buf)

    def iic_readinto(self, buf, *, start=0, end=None):
        self.i2c.readfrom_into(self.i2c_address, buf)
        
    def rdSensorReg8_8(self,addr):
        buffer=bytearray(1)
        buffer[0]=addr
        self.iic_write(buffer)
        self.iic_readinto(buffer)
        return buffer[0]
    
    def Spi_Test(self):
        while True:
            self.Spi_write(0X00,0X56)
            value=self.Spi_read(0X00)
            if(value[0]==0X56):
                print('SPI interface OK')
                break
            else:
                print('SPI interface Error')
            utime.sleep(1)

    def Camera_Init(self):
        if self.CameraType==OV5642:
            self.wrSensorReg16_8(0x3008, 0x80)
            if self.CameraMode == RAW:
                self.wrSensorRegs16_8(OV5642_1280x960_RAW)
                self.wrSensorRegs16_8(OV5642_640x480_RAW)
            else:
                self.wrSensorRegs16_8(OV5642_QVGA_Preview1)
                self.wrSensorRegs16_8(OV5642_QVGA_Preview2)
                utime.sleep(0.1)
                if self.CameraMode == JPEG:
                    utime.sleep(0.1)
                    self.wrSensorRegs16_8(OV5642_JPEG_Capture_QSXGA)
                    #Set resolution
                    self.wrSensorRegs16_8(ov5642_1280x960)
                    utime.sleep(0.1)
                    self.wrSensorReg16_8(0x3818, 0xa8)
                    self.wrSensorReg16_8(0x3621, 0x10)
                    self.wrSensorReg16_8(0x3801, 0xb0)
                    self.wrSensorReg16_8(0x4407, 0x04)
                else:
                    reg_val = 0
                    self.wrSensorReg16_8(0x4740, 0x21)
                    self.wrSensorReg16_8(0x501e, 0x2a)
                    self.wrSensorReg16_8(0x5002, 0xf8)
                    self.wrSensorReg16_8(0x501f, 0x01)
                    self.wrSensorReg16_8(0x4300, 0x61)
                    reg_val=self.rdSensorReg16_8(0x3818)
                    self.wrSensorReg16_8(0x3818, (reg_val | 0x60) & 0xff)
                    reg_val=self.rdSensorReg16_8(0x3621)
                    self.wrSensorReg16_8(0x3621, reg_val & 0xdf)            
        else:
            pass

        # Reglages CPLD (ArduChip) indispensables a la capture FIFO,
        # absents de ce portage jusqu'ici bien que les constantes existent.
        self.Spi_write(ARDUCHIP_TIM, VSYNC_LEVEL_MASK)  # polarite VSYNC = active HIGH
        self.Spi_write(ARDUCHIP_FRAMES, 0x00)           # 1 trame par capture
        
    def Spi_write(self,address,value):
        maskbits = 0x80
        buffer=bytearray(2)
        buffer[0]=address | maskbits
        buffer[1]=value
        self.SPI_CS_LOW()
        self.spi_write(buffer)
        self.SPI_CS_HIGH()
        
    def Spi_read(self,address):
        maskbits = 0x7f
        buffer=bytearray(1)
        buffer[0]=address & maskbits
        self.SPI_CS_LOW()
        self.spi_write(buffer)
        self.spi_readinto(buffer)
        self.SPI_CS_HIGH()
        return buffer

    def spi_write(self, buf, *, start=0, end=None):
        self.spi.write(buf)

    def spi_readinto(self, buf, *, start=0, end=None):
        self.spi.readinto(buf)
        
    def get_bit(self,addr,bit):
        value=self.Spi_read(addr)[0]
        return value&bit
  
    def SPI_CS_LOW(self):
        self.SPI_CS.value(False)
        
    def SPI_CS_HIGH(self):
        self.SPI_CS.value(True)
        
    def set_fifo_burst(self):
        buffer=bytearray(1)
        buffer[0]=0x3c
        self.spi.write(buffer)
        
    def clear_fifo_flag(self):
        self.Spi_write(0x04,0x01)
        
    def flush_fifo(self):
        self.Spi_write(0x04,0x01)
        
    def start_capture(self):
        self.Spi_write(0x04,0x02)
        
    def read_fifo_length(self):
        len1=self.Spi_read(0x42)[0]
        len2=self.Spi_read(0x43)[0]
        len3=self.Spi_read(0x44)[0]
        len3=len3 & 0x7f
        lenght=((len3<<16)|(len2<<8)|(len1))& 0x07fffff
        return lenght
    
    def wrSensorRegs8_8(self,reg_value):
        for data in reg_value:
            addr = data[0]
            val = data[1]
            if (addr == 0xff and val == 0xff):
                return
            self.wrSensorReg8_8(addr, val)
            utime.sleep(0.001)
            
    def wrSensorRegs16_8(self,reg_value):
        for data in reg_value:
            addr = data[0]
            val = data[1]
            if (addr == 0xffff and val == 0xff):
                return
            self.wrSensorReg16_8(addr, val)
            utime.sleep(0.003)
            
    def set_format(self,mode):
        if mode==BMP or mode==JPEG or mode==RAW:   
            self.CameraMode=mode
            
    def set_bit(self,addr,bit):
        temp=self.Spi_read(addr)[0]
        self.Spi_write(addr,temp&(~bit))

    def OV5642_set_JPEG_size(self,size):
        if size== OV5642_320x240:
          self.wrSensorRegs16_8(ov5642_320x240)
        elif size== OV5642_640x480:
          self.wrSensorRegs16_8(ov5642_640x480)     
        elif size== OV5642_1024x768:
          self.wrSensorRegs16_8(ov5642_1024x768)      
        elif size== OV5642_1280x960:
          self.wrSensorRegs16_8(ov5642_1280x960)      
        elif size== OV5642_1600x1200:
          self.wrSensorRegs16_8(ov5642_1600x1200)      
        elif size== OV5642_2048x1536:
          self.wrSensorRegs16_8(ov5642_2048x1536)      
        elif size== OV5642_2592x1944:
          self.wrSensorRegs16_8(ov5642_2592x1944)      
        else:
          self.wrSensorRegs16_8(ov5642_320x240)

    def OV5642_set_Compress_quality(self,quality):
        if quality== high_quality:
            self.wrSensorReg16_8(0x4407, 0x02)
        elif quality== default_quality:
            self.wrSensorReg16_8(0x4407, 0x04)
        elif quality== low_quality:
            self.wrSensorReg16_8(0x4407, 0x08)
